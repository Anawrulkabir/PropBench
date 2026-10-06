//! The worker operations of protocol v2 (`propbench.worker.server.METHODS`, implemented in `propbench.api`).
//!
//! The GUI, the CLI and the Python package reach the same operations; the engine only forwards JSON. `Method` is the
//! whitelist: nothing else can be sent to the worker through `Engine::invoke`.

use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{Engine, EngineError};

/// One worker operation. Serialised as its RPC name, e.g. `"model.fit"`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Method {
    #[serde(rename = "fluids")]
    Fluids,
    #[serde(rename = "properties")]
    Properties,
    #[serde(rename = "dataset.preview")]
    DatasetPreview,
    #[serde(rename = "dataset.import")]
    DatasetImport,
    #[serde(rename = "dataset.check")]
    DatasetCheck,
    #[serde(rename = "model.kinds")]
    ModelKinds,
    #[serde(rename = "model.default")]
    ModelDefault,
    #[serde(rename = "model.predict")]
    ModelPredict,
    #[serde(rename = "model.fit")]
    ModelFit,
    #[serde(rename = "study.validate")]
    StudyValidate,
    #[serde(rename = "selection.lock")]
    SelectionLock,
    #[serde(rename = "selection.select")]
    SelectionSelect,
    #[serde(rename = "consistency.analyze")]
    ConsistencyAnalyze,
    #[serde(rename = "model.references")]
    ModelReferences,
    #[serde(rename = "model.compare")]
    ModelCompare,
}

impl Method {
    pub const ALL: [Method; 15] = [
        Method::Fluids,
        Method::Properties,
        Method::DatasetPreview,
        Method::DatasetImport,
        Method::DatasetCheck,
        Method::ModelKinds,
        Method::ModelDefault,
        Method::ModelPredict,
        Method::ModelFit,
        Method::StudyValidate,
        Method::SelectionLock,
        Method::SelectionSelect,
        Method::ConsistencyAnalyze,
        Method::ModelReferences,
        Method::ModelCompare,
    ];

    /// The JSON-RPC method name.
    pub fn name(self) -> &'static str {
        match self {
            Method::Fluids => "fluids",
            Method::Properties => "properties",
            Method::DatasetPreview => "dataset.preview",
            Method::DatasetImport => "dataset.import",
            Method::DatasetCheck => "dataset.check",
            Method::ModelKinds => "model.kinds",
            Method::ModelDefault => "model.default",
            Method::ModelPredict => "model.predict",
            Method::ModelFit => "model.fit",
            Method::StudyValidate => "study.validate",
            Method::SelectionLock => "selection.lock",
            Method::SelectionSelect => "selection.select",
            Method::ConsistencyAnalyze => "consistency.analyze",
            Method::ModelReferences => "model.references",
            Method::ModelCompare => "model.compare",
        }
    }

    pub fn from_name(name: &str) -> Option<Method> {
        Method::ALL.into_iter().find(|m| m.name() == name)
    }

    /// Time limit of one request: fits and validation studies may run long, everything else gets the default.
    pub fn timeout(self, default: Duration) -> Duration {
        match self {
            Method::ModelFit => default.max(Duration::from_secs(15 * 60)),
            Method::StudyValidate => default.max(Duration::from_secs(4 * 60 * 60)),
            Method::ConsistencyAnalyze | Method::ModelCompare => default.max(Duration::from_secs(10 * 60)),
            _ => default,
        }
    }
}

impl Engine {
    /// Run one worker operation. `params` must be a JSON object (or null for none).
    pub async fn invoke(&self, method: Method, params: Value) -> Result<Value, EngineError> {
        let params = match params {
            Value::Null => Value::Object(serde_json::Map::new()),
            Value::Object(_) => params,
            _ => {
                return Err(EngineError::Rpc {
                    code: EngineError::INVALID_PARAMS,
                    message: "params must be a JSON object".into(),
                });
            }
        };
        let limit = method.timeout(self.request_timeout());
        self.call_with_timeout(method.name(), params, limit).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_round_trip_and_match_serde() {
        for method in Method::ALL {
            assert_eq!(Method::from_name(method.name()), Some(method));
            assert_eq!(
                serde_json::to_value(method).ok(),
                Some(Value::String(method.name().into()))
            );
        }
        assert_eq!(Method::from_name("property"), None);
        assert_eq!(Method::from_name("os.system"), None);
    }

    #[test]
    fn long_methods_get_long_timeouts() {
        let d = Duration::from_secs(30);
        assert_eq!(Method::Fluids.timeout(d), d);
        assert!(Method::ModelFit.timeout(d) >= Duration::from_secs(600));
        assert!(Method::StudyValidate.timeout(d) >= Method::ModelFit.timeout(d));
    }
}
