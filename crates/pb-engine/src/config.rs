use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::EngineError;

/// Environment variable that overrides which Python runs the worker (used by tests and CI).
pub const WORKER_PYTHON_ENV: &str = "PB_WORKER_PYTHON";

/// Environment variables passed through to the worker; everything else is cleared (README §4c, isolation).
const ENV_ALLOWLIST: &[&str] = &[
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "LANG",
    "LC_ALL",
    // PropBench's own settings: components folder and component registry (README §2b).
    "PB_COMPONENTS_DIR",
    "PB_ENVS_DIR",
    "PB_REGISTRY_URL",
];

/// How to start a worker process.
#[derive(Debug, Clone)]
pub struct WorkerCommand {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    /// Environment of the worker. The parent environment is cleared first.
    pub env: Vec<(OsString, OsString)>,
}

impl WorkerCommand {
    /// The `propbench` worker in isolated mode: no user site-packages, no `PYTHON*` variables, no bytecode writes.
    pub fn python_worker(python: PathBuf) -> Self {
        Self::python(python, ["-I", "-B", "-X", "utf8", "-m", "propbench.worker"])
    }

    /// Any Python invocation with the isolated environment (used for tests of the supervisor).
    pub fn python<I, S>(python: PathBuf, args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<OsString>,
    {
        let env = ENV_ALLOWLIST
            .iter()
            .filter_map(|key| std::env::var_os(key).map(|value| (OsString::from(key), value)))
            .collect();
        Self {
            program: python,
            args: args.into_iter().map(Into::into).collect(),
            env,
        }
    }
}

impl WorkerCommand {
    /// The same command with one more (or a replaced) environment variable.
    pub fn with_env(mut self, key: impl Into<OsString>, value: impl Into<OsString>) -> Self {
        let key = key.into();
        self.env.retain(|(k, _)| *k != key);
        self.env.push((key, value.into()));
        self
    }
}

/// A worker on another machine, reached with the system's OpenSSH client and the user's own keys (README §4d).
/// Nothing listens on the network: the worker's JSON-RPC runs over the SSH session's stdin and stdout.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct RemoteTarget {
    pub host: String,
    #[serde(default)]
    pub user: Option<String>,
    #[serde(default)]
    pub port: Option<u16>,
    /// Private key file; by default the SSH agent and the user's SSH configuration decide.
    #[serde(default)]
    pub identity: Option<PathBuf>,
    /// Python of the PropBench installation on the remote machine (with the `propbench` package).
    pub python: String,
}

impl RemoteTarget {
    fn check(&self) -> Result<(), EngineError> {
        let ok_name = |s: &str| {
            !s.is_empty()
                && !s.starts_with('-')
                && s.chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_' | ':' | '[' | ']'))
        };
        if !ok_name(&self.host) || self.user.as_deref().is_some_and(|u| !ok_name(u)) {
            return Err(EngineError::Startup(format!(
                "invalid remote host or user `{}`",
                self.destination()
            )));
        }
        if self.python.trim().is_empty() || self.python.contains(['\n', '\0']) {
            return Err(EngineError::Startup("invalid remote Python path".into()));
        }
        Ok(())
    }

    /// `user@host` or `host`.
    pub fn destination(&self) -> String {
        match &self.user {
            Some(u) => format!("{u}@{}", self.host),
            None => self.host.clone(),
        }
    }

    /// The command line run on the remote machine (POSIX shell quoting).
    pub fn remote_command(&self) -> String {
        let quoted = format!("'{}'", self.python.replace('\'', "'\\''"));
        format!("{quoted} -I -B -X utf8 -m propbench.worker")
    }
}

impl WorkerCommand {
    /// The worker on `target`, started through `ssh` (the first element of `ssh` is the program, the rest are
    /// leading arguments; normally just `["ssh"]`). Batch mode: never asks for a password interactively.
    pub fn ssh(target: &RemoteTarget, ssh: &[OsString]) -> Result<Self, EngineError> {
        target.check()?;
        let (program, lead) = ssh
            .split_first()
            .ok_or_else(|| EngineError::Startup("no ssh program".into()))?;
        let mut args: Vec<OsString> = lead.to_vec();
        for a in ["-T", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30"] {
            args.push(a.into());
        }
        if let Some(port) = target.port {
            args.push("-p".into());
            args.push(port.to_string().into());
        }
        if let Some(identity) = &target.identity {
            args.push("-i".into());
            args.push(identity.clone().into_os_string());
        }
        args.push("--".into());
        args.push(target.destination().into());
        args.push(target.remote_command().into());
        let env = ENV_ALLOWLIST
            .iter()
            .chain(["SSH_AUTH_SOCK", "PATH"].iter())
            .filter_map(|key| std::env::var_os(key).map(|value| (OsString::from(*key), value)))
            .collect();
        Ok(Self {
            program: PathBuf::from(program),
            args,
            env,
        })
    }
}

/// Engine settings.
#[derive(Debug, Clone)]
pub struct EngineConfig {
    pub worker: WorkerCommand,
    /// Time allowed for the worker to send its `ready` notification.
    pub startup_timeout: Duration,
    /// Time allowed for one request; on expiry the worker is stopped and restarted on the next call.
    pub request_timeout: Duration,
    /// More than this many failures within `failure_window` puts the engine into the failed state.
    pub max_failures: usize,
    pub failure_window: Duration,
}

impl EngineConfig {
    pub fn new(worker: WorkerCommand) -> Self {
        Self {
            worker,
            startup_timeout: Duration::from_secs(60),
            request_timeout: Duration::from_secs(30),
            max_failures: 3,
            failure_window: Duration::from_secs(60),
        }
    }
}

/// Path of the interpreter inside a bundled standalone Python directory.
pub fn bundled_python(python_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        python_dir.join("python.exe")
    } else {
        python_dir.join("bin").join("python3")
    }
}

/// Find the Python that runs the worker: `PB_WORKER_PYTHON`, then the bundled Python (if a directory is given),
/// then, in debug builds only, the development environment `worker/.venv` created by `uv sync --project worker`.
pub fn resolve_worker_python(bundled_dir: Option<&Path>) -> Result<PathBuf, EngineError> {
    let mut tried = Vec::new();
    if let Some(path) = std::env::var_os(WORKER_PYTHON_ENV) {
        let path = PathBuf::from(path);
        if path.is_file() {
            return Ok(path);
        }
        return Err(EngineError::PythonNotFound(format!(
            "{WORKER_PYTHON_ENV}={} is not a file",
            path.display()
        )));
    }
    if let Some(dir) = bundled_dir {
        let path = bundled_python(dir);
        if path.is_file() {
            return Ok(path);
        }
        tried.push(path);
    }
    if cfg!(debug_assertions) {
        let venv = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../worker/.venv");
        let path = if cfg!(windows) {
            venv.join("Scripts").join("python.exe")
        } else {
            venv.join("bin").join("python")
        };
        if path.is_file() {
            return Ok(path);
        }
        tried.push(path);
    }
    let tried: Vec<String> = tried.iter().map(|p| p.display().to_string()).collect();
    Err(EngineError::PythonNotFound(format!(
        "set {WORKER_PYTHON_ENV} or run `uv sync --project worker` (tried: {})",
        tried.join(", ")
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ssh_command_has_no_injection_and_quotes_the_remote_python() -> Result<(), EngineError> {
        let target = RemoteTarget {
            host: "gpu01.lab.example".into(),
            user: Some("me".into()),
            port: Some(2222),
            identity: None,
            python: "/opt/prop bench/bin/python".into(),
        };
        let cmd = WorkerCommand::ssh(&target, &["ssh".into()])?;
        let args: Vec<String> = cmd.args.iter().map(|a| a.to_string_lossy().into_owned()).collect();
        assert_eq!(cmd.program, PathBuf::from("ssh"));
        let dd = args.iter().position(|a| a == "--").unwrap_or(usize::MAX);
        assert_eq!(args[dd + 1], "me@gpu01.lab.example");
        assert_eq!(
            args[dd + 2],
            "'/opt/prop bench/bin/python' -I -B -X utf8 -m propbench.worker"
        );
        assert!(args.contains(&"BatchMode=yes".to_owned()));
        for bad in ["-oProxyCommand=evil", "a b", ""] {
            let t = RemoteTarget {
                host: bad.into(),
                ..target.clone()
            };
            assert!(WorkerCommand::ssh(&t, &["ssh".into()]).is_err(), "{bad}");
        }
        Ok(())
    }

    #[test]
    fn worker_command_runs_isolated_module() {
        let cmd = WorkerCommand::python_worker(PathBuf::from("python"));
        let args: Vec<_> = cmd.args.iter().map(|a| a.to_string_lossy().into_owned()).collect();
        assert_eq!(args, ["-I", "-B", "-X", "utf8", "-m", "propbench.worker"]);
        assert!(
            cmd.env
                .iter()
                .all(|(k, _)| ENV_ALLOWLIST.contains(&k.to_string_lossy().as_ref()))
        );
    }

    #[test]
    fn bundled_python_layout() {
        let p = bundled_python(Path::new("res/python"));
        if cfg!(windows) {
            assert!(p.ends_with("python.exe"));
        } else {
            assert!(p.ends_with("bin/python3"));
        }
    }
}
