//! Supervisor behaviour against small scripted workers (run with the worker's own Python, isolated mode).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::time::Duration;

use pb_engine::{Engine, EngineConfig, EngineError, WorkerCommand, resolve_worker_python};
use serde_json::json;

const READY: &str =
    r#"{"jsonrpc":"2.0","method":"ready","params":{"protocol":1,"propbench":"t","python":"t","coolprop":"t"}}"#;

/// An engine whose worker is the given Python script (after printing READY unless the script does it).
fn engine(script: &str, tweak: impl FnOnce(&mut EngineConfig)) -> Engine {
    let python = resolve_worker_python(None).expect("worker Python: run `uv sync --project worker`");
    let mut config = EngineConfig::new(WorkerCommand::python(python, ["-I", "-B", "-c", script]));
    config.startup_timeout = Duration::from_secs(30);
    tweak(&mut config);
    Engine::new(config)
}

fn with_ready(body: &str) -> String {
    format!("import sys, json\nprint({READY:?}, flush=True)\n{body}")
}

#[tokio::test]
async fn echo_worker_round_trip_and_concurrent_ids() {
    let script = with_ready(
        "for line in sys.stdin:\n    r = json.loads(line)\n    print(json.dumps({'jsonrpc': '2.0', 'id': r['id'], 'result': r['params']}), flush=True)\n",
    );
    let engine = engine(&script, |_| {});
    let calls = (0..20).map(|i| engine.call("echo", json!({ "i": i })));
    let results = futures_join_all(calls).await;
    for (i, result) in results.into_iter().enumerate() {
        assert_eq!(result.unwrap(), json!({ "i": i }));
    }
    assert_eq!(engine.worker_info().await.unwrap().propbench, "t");
    engine.shutdown().await;
    assert!(engine.worker_info().await.is_none());
}

#[tokio::test]
async fn crashing_worker_is_restarted_then_marked_failed() {
    let script = with_ready("sys.stdin.readline()\nprint('dying', file=sys.stderr, flush=True)\nsys.exit(3)\n");
    let engine = engine(&script, |c| c.max_failures = 2);
    for _ in 0..3 {
        // initial start + two restarts are allowed
        let err = engine.call("x", json!({})).await.unwrap_err();
        assert!(
            matches!(&err, EngineError::WorkerExited(m) if m.contains("dying")),
            "{err}"
        );
    }
    let err = engine.call("x", json!({})).await.unwrap_err();
    assert!(matches!(err, EngineError::Failed { .. }), "{err}");
}

#[tokio::test]
async fn hung_worker_times_out_and_is_replaced() {
    let script = with_ready("for line in sys.stdin:\n    pass\n");
    let engine = engine(&script, |c| c.request_timeout = Duration::from_millis(500));
    let err = engine.call("x", json!({})).await.unwrap_err();
    assert!(matches!(err, EngineError::Timeout(_)), "{err}");
    // the next call starts a fresh worker (which hangs again)
    let err = engine.call("x", json!({})).await.unwrap_err();
    assert!(matches!(err, EngineError::Timeout(_)), "{err}");
}

#[tokio::test]
async fn garbage_on_stdout_is_a_protocol_error() {
    let script = with_ready("sys.stdin.readline()\nprint('this is not json', flush=True)\nsys.stdin.readline()\n");
    let engine = engine(&script, |_| {});
    let err = engine.call("x", json!({})).await.unwrap_err();
    assert!(
        matches!(&err, EngineError::Protocol(m) if m.contains("this is not json")),
        "{err}"
    );
}

#[tokio::test]
async fn worker_that_dies_before_ready_reports_its_stderr() {
    let engine = engine("import sys\nsys.exit('cannot import CoolProp')", |_| {});
    let err = engine.start().await.unwrap_err();
    assert!(
        matches!(&err, EngineError::Startup(m) if m.contains("cannot import CoolProp")),
        "{err}"
    );
}

#[tokio::test]
async fn protocol_version_mismatch_is_rejected() {
    let ready = READY.replace("\"protocol\":1", "\"protocol\":99");
    let engine = engine(&format!("print({ready:?}, flush=True)\ninput()"), |_| {});
    let err = engine.start().await.unwrap_err();
    assert!(
        matches!(&err, EngineError::Startup(m) if m.contains("protocol 99")),
        "{err}"
    );
}

#[tokio::test]
async fn missing_program_is_a_spawn_error() {
    let engine = Engine::new(EngineConfig::new(WorkerCommand::python_worker(
        "/nonexistent/python".into(),
    )));
    assert!(matches!(engine.start().await, Err(EngineError::Spawn { .. })));
}

/// Minimal join_all without an extra dependency: run the futures concurrently on the current task.
async fn futures_join_all<F: std::future::Future>(futures: impl Iterator<Item = F>) -> Vec<F::Output> {
    let mut set = Vec::new();
    for f in futures {
        set.push(Box::pin(f));
    }
    let mut outputs: Vec<Option<F::Output>> = set.iter().map(|_| None).collect();
    std::future::poll_fn(|cx| {
        let mut done = true;
        for (fut, out) in set.iter_mut().zip(outputs.iter_mut()) {
            if out.is_none() {
                match fut.as_mut().poll(cx) {
                    std::task::Poll::Ready(v) => *out = Some(v),
                    std::task::Poll::Pending => done = false,
                }
            }
        }
        if done {
            std::task::Poll::Ready(())
        } else {
            std::task::Poll::Pending
        }
    })
    .await;
    outputs.into_iter().map(|o| o.unwrap()).collect()
}
