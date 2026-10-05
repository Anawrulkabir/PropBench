//! End-to-end: pb-engine starts the real `propbench` worker and computes the M0 acceptance value over JSON-RPC.
//!
//! Runs against the development environment, or against the bundled Python when `PB_WORKER_PYTHON` points to it (CI
//! does both). Fails, rather than skips, when no worker Python is available.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use pb_engine::{Engine, EngineConfig, EngineError, PropertyRequest, WorkerCommand, resolve_worker_python};

/// R134a at 300 K and 1 MPa, CoolProp HEOS; given to 2 decimals.
const R134A_DENSITY_300K_1MPA: f64 = 1201.53;

fn engine() -> Engine {
    let python = resolve_worker_python(None).expect("worker Python: run `uv sync --project worker`");
    Engine::new(EngineConfig::new(WorkerCommand::python_worker(python)))
}

fn r134a(output: &str) -> PropertyRequest {
    PropertyRequest {
        fluid: "R134a".into(),
        pair: "PT_INPUTS".into(),
        values: [1.0e6, 300.0],
        output: output.into(),
    }
}

#[tokio::test]
async fn acceptance_r134a_density_over_rpc() {
    let engine = engine();
    let info = engine.start().await.unwrap();
    assert_eq!(info.protocol, pb_engine::PROTOCOL_VERSION);
    assert!(info.python.starts_with("3.12"), "worker Python {}", info.python);

    let result = engine.property(&r134a("Dmass")).await.unwrap();
    assert!(
        (result.value - R134A_DENSITY_300K_1MPA).abs() < 0.005,
        "density {}",
        result.value
    );
    assert_eq!(result.backend, "CoolProp::HEOS");
    assert_eq!(result.backend_version, info.coolprop);

    // The worker survives a backend error and keeps answering.
    let err = engine
        .property(&PropertyRequest {
            fluid: "NotAFluid".into(),
            ..r134a("Dmass")
        })
        .await
        .unwrap_err();
    assert!(
        matches!(&err, EngineError::Rpc { code: EngineError::BACKEND_ERROR, message } if message.contains("NotAFluid"))
    );
    let again = engine.property(&r134a("Dmass")).await.unwrap();
    assert_eq!(again.value, result.value);

    engine.shutdown().await;
}

#[tokio::test]
async fn non_finite_values_are_rejected_before_the_worker() {
    let engine = engine();
    let err = engine
        .property(&PropertyRequest {
            values: [f64::NAN, 300.0],
            ..r134a("Dmass")
        })
        .await
        .unwrap_err();
    assert!(matches!(
        err,
        EngineError::Rpc {
            code: EngineError::INVALID_PARAMS,
            ..
        }
    ));
    assert!(
        engine.worker_info().await.is_none(),
        "no worker should have been started"
    );
}
