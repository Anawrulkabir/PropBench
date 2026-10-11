//! Job graph with the result cache: a worker crash mid-study loses no finished job and the study resumes;
//! a second run is served from the cache; cancel stops the running job and skips the rest.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use pb_engine::store::ResultCache;
use pb_engine::{Engine, EngineConfig, Job, JobGraph, JobOutcome, Method, WorkerCommand, resolve_worker_python};
use serde_json::json;

const READY: &str =
    r#"{"jsonrpc":"2.0","method":"ready","params":{"protocol":2,"propbench":"t","python":"t","coolprop":"t"}}"#;

fn scratch(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("pb-jobs-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// A worker that answers `{"n": n}` with `{"square": n*n}`, appends every computed n to `log`, crashes on the
/// first attempt at `crash_on`, and sleeps for a long time on `hang_on`.
fn engine(dir: &Path, crash_on: i64, hang_on: i64) -> Engine {
    let log = dir.join("computed.txt");
    let marker = dir.join("crashed");
    let marker = format!("{:?}", marker.display().to_string());
    let log = format!("{:?}", log.display().to_string());
    let script = [
        "import sys, json, os, time".to_owned(),
        format!("print({READY:?}, flush=True)"),
        "for line in sys.stdin:".to_owned(),
        "    r = json.loads(line)".to_owned(),
        "    n = r['params']['n']".to_owned(),
        format!("    if n == {crash_on} and not os.path.exists({marker}):"),
        format!("        open({marker}, 'w').close()"),
        "        os._exit(3)".to_owned(),
        format!("    if n == {hang_on}:"),
        "        time.sleep(60)".to_owned(),
        format!("    open({log}, 'a').write(str(n) + '\\n')"),
        "    print(json.dumps({'jsonrpc': '2.0', 'id': r['id'], 'result': {'square': n * n}}), flush=True)".to_owned(),
    ]
    .join("\n");
    let python = resolve_worker_python(None).expect("worker Python: run `uv sync --project worker`");
    let mut config = EngineConfig::new(WorkerCommand::python(python, ["-I", "-B", "-c", &script]));
    config.startup_timeout = Duration::from_secs(30);
    Engine::new(config)
}

fn computed(dir: &Path) -> Vec<i64> {
    std::fs::read_to_string(dir.join("computed.txt"))
        .unwrap_or_default()
        .lines()
        .map(|l| l.parse().unwrap())
        .collect()
}

fn study(n: i64) -> JobGraph {
    let mut g = JobGraph::new();
    for i in 1..=n {
        let after = if i > 1 { vec![format!("fit {}", i - 1)] } else { vec![] };
        g.add(Job {
            id: format!("fit {i}"),
            method: Method::ModelFit,
            params: json!({ "n": i }),
            after,
        })
        .unwrap();
    }
    g
}

#[tokio::test]
async fn crash_mid_study_loses_nothing_and_rerun_is_cached() {
    let dir = scratch("resume");
    let cache = ResultCache::open(&dir.join("cache.sqlite")).unwrap();
    let engine = engine(&dir, 2, -1);
    let never = AtomicBool::new(false);
    let mut events = Vec::new();
    let out = study(3)
        .run(&engine, Some(&cache), &never, |e| events.push(e.clone()))
        .await;
    for i in 1..=3 {
        assert_eq!(
            out[&format!("fit {i}")],
            JobOutcome::Done {
                result: json!({ "square": i * i }),
                cached: false
            }
        );
    }
    assert_eq!(
        computed(&dir),
        vec![1, 2, 3],
        "job 2 was retried on a fresh worker after the crash"
    );
    assert_eq!(events.len(), 3);
    engine.shutdown().await;

    // The app restarts (new engine, same cache file): nothing is recomputed.
    let cache = ResultCache::open(&dir.join("cache.sqlite")).unwrap();
    let engine2 = self::engine(&dir, -1, -1);
    let again = study(4).run(&engine2, Some(&cache), &never, |_| {}).await;
    assert!(matches!(again["fit 2"], JobOutcome::Done { cached: true, .. }));
    assert!(matches!(again["fit 4"], JobOutcome::Done { cached: false, .. }));
    assert_eq!(computed(&dir), vec![1, 2, 3, 4], "only the new job ran");
    engine2.shutdown().await;
}

#[tokio::test]
async fn cancel_stops_the_running_job_and_skips_the_rest() {
    let dir = scratch("cancel");
    let engine = Arc::new(engine(&dir, -1, 2));
    let cancel = Arc::new(AtomicBool::new(false));
    let run = {
        let (engine, cancel) = (Arc::clone(&engine), Arc::clone(&cancel));
        tokio::spawn(async move { study(3).run(&engine, None, &cancel, |_| {}).await })
    };
    // Wait until job 1 is done and job 2 hangs, then cancel.
    for _ in 0..200 {
        if computed(&dir) == vec![1] {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    tokio::time::sleep(Duration::from_millis(200)).await;
    cancel.store(true, Ordering::SeqCst);
    engine.cancel().await;
    let out = tokio::time::timeout(Duration::from_secs(20), run)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(out["fit 1"], JobOutcome::Done { .. }));
    assert_eq!(
        out["fit 2"],
        JobOutcome::Skipped {
            reason: "cancelled".into()
        }
    );
    assert!(matches!(out["fit 3"], JobOutcome::Skipped { .. }));
    // The engine is usable again after a cancel (a fresh worker starts) and a cancel is not a failure.
    cancel.store(false, Ordering::SeqCst);
    let (value, _) = engine
        .invoke_cached(Method::ModelFit, json!({ "n": 5 }), None)
        .await
        .unwrap();
    assert_eq!(value, json!({ "square": 25 }));
    engine.shutdown().await;
}
