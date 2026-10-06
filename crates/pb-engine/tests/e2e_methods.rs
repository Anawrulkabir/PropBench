//! End-to-end: protocol v2 operations through the real worker (fluids, models, batched properties, errors).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use pb_engine::{Engine, EngineConfig, EngineError, Method, WorkerCommand, resolve_worker_python};
use serde_json::json;

fn engine() -> Engine {
    let python = resolve_worker_python(None).expect("worker Python: run `uv sync --project worker`");
    Engine::new(EngineConfig::new(WorkerCommand::python_worker(python)))
}

#[tokio::test]
async fn v2_methods_answer() {
    let engine = engine();
    let fluids = engine.invoke(Method::Fluids, serde_json::Value::Null).await.unwrap();
    assert!(fluids["fluids"].as_array().unwrap().iter().any(|f| f == "R134a"));

    let batch = engine
        .invoke(
            Method::Properties,
            json!({"fluid": "R134a", "pair": "PT_INPUTS", "values1": [1.0e6], "values2": [300.0], "outputs": ["Dmass"]}),
        )
        .await
        .unwrap();
    assert!(
        (batch["outputs"]["Dmass"][0].as_f64().unwrap() - 1201.53).abs() < 0.005,
        "{batch}"
    );

    let model = engine
        .invoke(
            Method::ModelDefault,
            json!({"kind": "ecs_viscosity", "fluid": "R236FA"}),
        )
        .await
        .unwrap();
    assert_eq!(model["model"]["kind"], "ecs_viscosity");

    let predicted = engine
        .invoke(
            Method::ModelPredict,
            json!({"model": model["model"], "temperature": [300.0], "pressure": [1.0e6]}),
        )
        .await
        .unwrap();
    assert!(predicted["values"][0].as_f64().unwrap() > 0.0);
    engine.shutdown().await;
}

#[tokio::test]
async fn v2_errors_are_typed() {
    let engine = engine();
    let err = engine
        .invoke(Method::ModelFit, json!({"model": {"kind": "nope"}, "datasets": []}))
        .await
        .unwrap_err();
    assert!(
        matches!(
            err,
            EngineError::Rpc {
                code: EngineError::PROPBENCH_ERROR,
                ..
            }
        ),
        "{err:?}"
    );
    let err = engine.invoke(Method::ModelDefault, json!({})).await.unwrap_err();
    assert!(
        matches!(
            err,
            EngineError::Rpc {
                code: EngineError::INVALID_PARAMS,
                ..
            }
        ),
        "{err:?}"
    );
    let err = engine.invoke(Method::Fluids, json!([1])).await.unwrap_err();
    assert!(
        matches!(
            err,
            EngineError::Rpc {
                code: EngineError::INVALID_PARAMS,
                ..
            }
        ),
        "{err:?}"
    );
    engine.shutdown().await;
}
