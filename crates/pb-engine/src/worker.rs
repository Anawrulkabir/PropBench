use std::collections::{HashMap, VecDeque};
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader, Lines};
use tokio::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command};
use tokio::sync::{Mutex, oneshot};
use tokio::task::JoinHandle;
use tokio::time::timeout;

use crate::rpc::{Incoming, Request};
use crate::{EngineConfig, EngineError, PROTOCOL_VERSION, PropertyRequest, PropertyResult, WorkerInfo};

/// Number of worker stderr lines kept to explain a crash.
const STDERR_TAIL_LINES: usize = 20;
/// Time to wait for a worker to exit after its stdin is closed.
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

/// Starts, supervises and talks to one Python worker. Cheap to share behind an `Arc`; all methods take `&self`.
///
/// The worker is started on first use. If it dies or stops answering, pending calls fail and the next call starts a
/// new worker, unless it failed more than `max_failures` times within `failure_window`.
pub struct Engine {
    config: EngineConfig,
    worker: Mutex<Option<Arc<Worker>>>,
    failures: StdMutex<VecDeque<Instant>>,
    next_id: AtomicU64,
}

impl Engine {
    pub fn new(config: EngineConfig) -> Self {
        Self {
            config,
            worker: Mutex::new(None),
            failures: StdMutex::new(VecDeque::new()),
            next_id: AtomicU64::new(1),
        }
    }

    /// Start the worker if it is not running and return the versions it reported.
    pub async fn start(&self) -> Result<WorkerInfo, EngineError> {
        Ok(self.ensure_worker().await?.info.clone())
    }

    /// Default time limit of one request.
    pub fn request_timeout(&self) -> Duration {
        self.config.request_timeout
    }

    /// Versions reported by the running worker, if one is running.
    pub async fn worker_info(&self) -> Option<WorkerInfo> {
        self.worker
            .lock()
            .await
            .as_ref()
            .filter(|w| w.is_alive())
            .map(|w| w.info.clone())
    }

    /// Compute one property at one state (SI units) in the worker.
    pub async fn property(&self, request: &PropertyRequest) -> Result<PropertyResult, EngineError> {
        if !request.values.iter().all(|v| v.is_finite()) {
            return Err(EngineError::Rpc {
                code: EngineError::INVALID_PARAMS,
                message: "input values must be finite numbers".into(),
            });
        }
        let params = serde_json::to_value(request).map_err(|e| EngineError::Protocol(e.to_string()))?;
        let result = self.call("property", params).await?;
        serde_json::from_value(result).map_err(|e| EngineError::Protocol(format!("bad property result: {e}")))
    }

    /// Send one JSON-RPC request to the worker and wait for its result.
    pub async fn call(&self, method: &str, params: Value) -> Result<Value, EngineError> {
        self.call_with_timeout(method, params, self.config.request_timeout)
            .await
    }

    /// Like `call`, with a time limit for this request (long fits and validation studies).
    pub async fn call_with_timeout(&self, method: &str, params: Value, limit: Duration) -> Result<Value, EngineError> {
        let worker = self.ensure_worker().await?;
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        worker.call(id, method, &params, limit).await
    }

    /// Cancel whatever the worker is doing: every pending call fails with `EngineError::Cancelled` and the worker
    /// is stopped. This is not counted as a failure; the next call starts a fresh worker.
    pub async fn cancel(&self) {
        let worker = self.worker.lock().await.take();
        if let Some(worker) = worker {
            close(&worker.pending, Closed::Cancelled);
            worker.kill().await;
        }
    }

    /// Stop the worker: close its stdin so it exits by itself, and kill it if it does not.
    pub async fn shutdown(&self) {
        if let Some(worker) = self.worker.lock().await.take() {
            worker.shutdown().await;
        }
    }

    async fn ensure_worker(&self) -> Result<Arc<Worker>, EngineError> {
        let mut guard = self.worker.lock().await;
        if let Some(worker) = guard.as_ref().filter(|w| w.is_alive()) {
            return Ok(Arc::clone(worker));
        }
        if let Some(dead) = guard.take() {
            dead.kill().await;
            self.note_failure();
        }
        self.check_failures()?;
        match Worker::spawn(&self.config).await {
            Ok(worker) => {
                let worker = Arc::new(worker);
                *guard = Some(Arc::clone(&worker));
                Ok(worker)
            }
            Err(err) => {
                if matches!(err, EngineError::Startup(_)) {
                    self.note_failure();
                }
                Err(err)
            }
        }
    }

    fn note_failure(&self) {
        lock(&self.failures).push_back(Instant::now());
    }

    fn check_failures(&self) -> Result<(), EngineError> {
        let window = self.config.failure_window;
        let mut failures = lock(&self.failures);
        while failures.front().is_some_and(|t| t.elapsed() > window) {
            failures.pop_front();
        }
        if failures.len() > self.config.max_failures {
            return Err(EngineError::Failed {
                failures: failures.len(),
                window,
            });
        }
        Ok(())
    }
}

type Reply = Result<Value, EngineError>;

/// Why a worker can no longer answer.
#[derive(Debug, Clone)]
enum Closed {
    Exited(String),
    Protocol(String),
    Cancelled,
}

impl Closed {
    fn to_error(&self) -> EngineError {
        match self {
            Closed::Exited(detail) => EngineError::WorkerExited(detail.clone()),
            Closed::Protocol(detail) => EngineError::Protocol(detail.clone()),
            Closed::Cancelled => EngineError::Cancelled,
        }
    }
}

#[derive(Default)]
struct Pending {
    calls: HashMap<u64, oneshot::Sender<Reply>>,
    closed: Option<Closed>,
}

struct Worker {
    child: Mutex<Child>,
    stdin: Mutex<Option<ChildStdin>>,
    pending: Arc<StdMutex<Pending>>,
    info: WorkerInfo,
}

impl Worker {
    async fn spawn(config: &EngineConfig) -> Result<Self, EngineError> {
        let cmd = &config.worker;
        let mut command = Command::new(&cmd.program);
        command
            .args(&cmd.args)
            .env_clear()
            .envs(cmd.env.iter().map(|(k, v)| (k, v)))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        #[cfg(windows)]
        {
            // CREATE_NO_WINDOW: no console window flashes up when the GUI starts the worker.
            command.creation_flags(0x0800_0000);
        }
        let mut child = command.spawn().map_err(|source| EngineError::Spawn {
            program: cmd.program.display().to_string(),
            source,
        })?;
        let (Some(stdin), Some(stdout), Some(stderr)) = (child.stdin.take(), child.stdout.take(), child.stderr.take())
        else {
            return Err(EngineError::Startup("worker stdio was not captured".into()));
        };

        let tail = Arc::new(StdMutex::new(VecDeque::new()));
        let stderr_task = tokio::spawn(drain_stderr(stderr, Arc::clone(&tail)));
        let mut lines = BufReader::new(stdout).lines();

        let first = match timeout(config.startup_timeout, lines.next_line()).await {
            Err(_) => {
                return Err(EngineError::Startup(format!(
                    "no ready message within {:?}{}",
                    config.startup_timeout,
                    tail_text(&tail)
                )));
            }
            Ok(line) => line?,
        };
        let Some(first) = first else {
            let _ = timeout(SHUTDOWN_GRACE, child.wait()).await;
            let _ = timeout(SHUTDOWN_GRACE, stderr_task).await;
            return Err(EngineError::Startup(format!(
                "worker exited before it was ready{}",
                tail_text(&tail)
            )));
        };
        let info = parse_ready(&first)?;

        let pending = Arc::new(StdMutex::new(Pending::default()));
        tokio::spawn(read_responses(lines, Arc::clone(&pending), tail, stderr_task));
        Ok(Self {
            child: Mutex::new(child),
            stdin: Mutex::new(Some(stdin)),
            pending,
            info,
        })
    }

    fn is_alive(&self) -> bool {
        lock(&self.pending).closed.is_none()
    }

    async fn call(&self, id: u64, method: &str, params: &Value, limit: Duration) -> Reply {
        let (tx, rx) = oneshot::channel();
        {
            let mut pending = lock(&self.pending);
            if let Some(closed) = &pending.closed {
                return Err(closed.to_error());
            }
            pending.calls.insert(id, tx);
        }
        let mut line = serde_json::to_string(&Request {
            jsonrpc: "2.0",
            id,
            method,
            params,
        })
        .map_err(|e| EngineError::Protocol(e.to_string()))?;
        line.push('\n');
        if let Err(err) = self.write(line.as_bytes()).await {
            lock(&self.pending).calls.remove(&id);
            return Err(lock(&self.pending).closed.as_ref().map_or(err, Closed::to_error));
        }
        match timeout(limit, rx).await {
            Ok(Ok(reply)) => reply,
            Ok(Err(_)) => Err(lock(&self.pending)
                .closed
                .as_ref()
                .map_or_else(|| EngineError::WorkerExited(String::new()), Closed::to_error)),
            Err(_) => {
                lock(&self.pending).calls.remove(&id);
                // A worker busy beyond the limit cannot serve anyone else: stop it; the next call restarts it.
                self.kill().await;
                Err(EngineError::Timeout(limit))
            }
        }
    }

    async fn write(&self, bytes: &[u8]) -> Result<(), EngineError> {
        let mut stdin = self.stdin.lock().await;
        let Some(stdin) = stdin.as_mut() else {
            return Err(EngineError::WorkerExited(": stdin closed".into()));
        };
        stdin.write_all(bytes).await?;
        stdin.flush().await?;
        Ok(())
    }

    async fn kill(&self) {
        // Mark the worker dead before killing it, so no new call is written to a dying process.
        close(&self.pending, Closed::Exited(": stopped by the engine".into()));
        let mut child = self.child.lock().await;
        let _ = child.start_kill();
        let _ = timeout(SHUTDOWN_GRACE, child.wait()).await;
    }

    async fn shutdown(&self) {
        self.stdin.lock().await.take();
        let mut child = self.child.lock().await;
        if timeout(SHUTDOWN_GRACE, child.wait()).await.is_err() {
            let _ = child.start_kill();
            let _ = timeout(SHUTDOWN_GRACE, child.wait()).await;
        }
    }
}

fn parse_ready(line: &str) -> Result<WorkerInfo, EngineError> {
    let bad = || EngineError::Startup(format!("expected a ready notification, got: {}", truncate(line)));
    let message: Incoming = serde_json::from_str(line).map_err(|_| bad())?;
    if message.jsonrpc != "2.0" || message.method.as_deref() != Some("ready") {
        return Err(bad());
    }
    let info: WorkerInfo = serde_json::from_value(message.params.unwrap_or(Value::Null)).map_err(|_| bad())?;
    if info.protocol != PROTOCOL_VERSION {
        return Err(EngineError::Startup(format!(
            "worker speaks protocol {}, engine expects {PROTOCOL_VERSION}",
            info.protocol
        )));
    }
    Ok(info)
}

async fn read_responses(
    mut lines: Lines<BufReader<ChildStdout>>,
    pending: Arc<StdMutex<Pending>>,
    tail: Arc<StdMutex<VecDeque<String>>>,
    stderr_task: JoinHandle<()>,
) {
    let closed = loop {
        let line = match lines.next_line().await {
            Ok(Some(line)) => line,
            Ok(None) => break None,
            Err(err) => break Some(Closed::Exited(format!(": {err}"))),
        };
        if line.trim().is_empty() {
            continue;
        }
        let message = match serde_json::from_str::<Incoming>(&line) {
            Ok(message) if message.jsonrpc == "2.0" => message,
            _ => {
                break Some(Closed::Protocol(format!(
                    "unexpected output from worker: {}",
                    truncate(&line)
                )));
            }
        };
        // Notifications (no id) are ignored for now; replies to calls that already timed out are dropped.
        let Some(id) = message.id.as_ref().and_then(Value::as_u64) else {
            continue;
        };
        let reply = match message.error {
            Some(error) => Err(EngineError::Rpc {
                code: error.code,
                message: error.message,
            }),
            None => Ok(message.result.unwrap_or(Value::Null)),
        };
        if let Some(tx) = lock(&pending).calls.remove(&id) {
            let _ = tx.send(reply);
        }
    };
    let closed = match closed {
        Some(closed) => closed,
        None => {
            // The worker closed stdout: let the stderr reader finish so the crash message is complete.
            let _ = timeout(SHUTDOWN_GRACE, stderr_task).await;
            Closed::Exited(tail_text(&tail))
        }
    };
    close(&pending, closed);
}

/// Mark a worker as unable to answer (the first reason wins) and fail every call still waiting for it.
fn close(pending: &StdMutex<Pending>, reason: Closed) {
    let mut pending = lock(pending);
    let reason = pending.closed.get_or_insert(reason).clone();
    for (_, tx) in pending.calls.drain() {
        let _ = tx.send(Err(reason.to_error()));
    }
}

async fn drain_stderr(stderr: ChildStderr, tail: Arc<StdMutex<VecDeque<String>>>) {
    let mut lines = BufReader::new(stderr).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        eprintln!("[propbench worker] {line}");
        let mut tail = lock(&tail);
        if tail.len() == STDERR_TAIL_LINES {
            tail.pop_front();
        }
        tail.push_back(line);
    }
}

fn tail_text(tail: &StdMutex<VecDeque<String>>) -> String {
    let tail = lock(tail);
    if tail.is_empty() {
        String::new()
    } else {
        format!("; worker stderr:\n{}", Vec::from(tail.clone()).join("\n"))
    }
}

fn truncate(line: &str) -> String {
    const MAX: usize = 200;
    match line.char_indices().nth(MAX) {
        Some((i, _)) => format!("{}…", &line[..i]),
        None => line.to_owned(),
    }
}

/// Lock a std mutex, ignoring poisoning: the protected data stays consistent because no code panics while holding
/// these locks.
fn lock<T>(mutex: &StdMutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ready_is_parsed_and_protocol_checked() {
        let ok = r#"{"jsonrpc":"2.0","method":"ready","params":{"protocol":2,"propbench":"0","python":"3.12","coolprop":"7"}}"#;
        assert_eq!(parse_ready(ok).unwrap().coolprop, "7");
        let wrong = ok.replace("\"protocol\":2", "\"protocol\":1");
        assert!(matches!(parse_ready(&wrong), Err(EngineError::Startup(m)) if m.contains("protocol 1")));
        assert!(matches!(parse_ready("hello"), Err(EngineError::Startup(_))));
        assert!(matches!(
            parse_ready(r#"{"jsonrpc":"2.0","id":1,"result":1}"#),
            Err(EngineError::Startup(_))
        ));
    }

    #[test]
    fn truncate_is_char_safe() {
        let long = "é".repeat(500);
        assert_eq!(truncate(&long).chars().count(), 201);
        assert_eq!(truncate("short"), "short");
    }
}
