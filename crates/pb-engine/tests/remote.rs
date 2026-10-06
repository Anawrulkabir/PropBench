//! Remote engine (README M4b acceptance): a worker reached through `ssh` gives results identical to the local
//! worker. CI has no SSH server, so `ssh` is replaced by a shim with the same command line that runs the remote
//! command locally; the engine side (arguments, stdio transport, protocol) is exactly what runs against OpenSSH.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::ffi::OsString;
use std::time::Duration;

use pb_engine::{Engine, EngineConfig, Method, RemoteTarget, WorkerCommand, resolve_worker_python};
use serde_json::json;

/// A stand-in for `ssh`: skips the options, takes `-- destination command` and runs the command locally.
const SSH_SHIM: &str = r#"
import shlex, subprocess, sys
args = sys.argv[1:]
cmd = shlex.split(args[args.index("--") + 2])
sys.exit(subprocess.call(cmd))
"#;

#[tokio::test]
async fn remote_results_are_identical_to_local() {
    let python = resolve_worker_python(None).expect("worker Python: run `uv sync --project worker`");
    let dir = std::env::temp_dir().join(format!("pb-remote-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let shim = dir.join("ssh_shim.py");
    std::fs::write(&shim, SSH_SHIM).unwrap();
    let target = RemoteTarget {
        host: "gpu01".into(),
        user: Some("me".into()),
        port: None,
        identity: None,
        python: python.display().to_string(),
    };
    let ssh: Vec<OsString> = vec![python.clone().into_os_string(), "-I".into(), shim.into_os_string()];
    let mut remote_cfg = EngineConfig::new(WorkerCommand::ssh(&target, &ssh).unwrap());
    remote_cfg.startup_timeout = Duration::from_secs(60);
    let remote = Engine::new(remote_cfg);
    let local = Engine::new(EngineConfig::new(WorkerCommand::python_worker(python)));

    let model = local
        .invoke(
            Method::ModelDefault,
            json!({"kind": "ecs_viscosity", "fluid": "R236FA"}),
        )
        .await
        .unwrap()["model"]
        .clone();
    let datasets = json!([{
        "schema_version": 1, "name": "d", "fluid": "R236FA", "quantity": "viscosity",
        "temperature": [260.0, 280.0, 300.0, 320.0, 340.0, 360.0], "pressure": [3e6, 3e6, 3e6, 3e6, 3e6, 3e6],
        "values": [4.1e-4, 3.4e-4, 2.8e-4, 2.3e-4, 1.9e-4, 1.5e-4]
    }]);
    let params = json!({"model": model, "datasets": datasets, "options": {"multistart": 2, "seed": 7}});
    let here = local.invoke(Method::ModelFit, params.clone()).await.unwrap();
    let there = remote.invoke(Method::ModelFit, params).await.unwrap();
    assert_eq!(
        here["summary"]["values"], there["summary"]["values"],
        "same fit on both engines"
    );
    assert_eq!(here, there, "identical results, bit for bit");
    local.shutdown().await;
    remote.shutdown().await;
}
