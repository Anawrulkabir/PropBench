use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Version of the stdio protocol spoken by `propbench.worker`; checked against the worker's `ready` notification.
pub const PROTOCOL_VERSION: u32 = 2;

/// One property at one state, SI units. `pair` is a CoolProp input-pair name (e.g. `PT_INPUTS`) and `values`
/// follow that pair's order; `output` is a CoolProp parameter name (e.g. `Dmass`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PropertyRequest {
    pub fluid: String,
    pub pair: String,
    pub values: [f64; 2],
    pub output: String,
}

/// A property value in SI units with the backend that produced it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PropertyResult {
    pub value: f64,
    pub output: String,
    pub backend: String,
    pub backend_version: String,
}

/// Versions reported by the worker when it starts (recorded for reproducibility).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorkerInfo {
    pub protocol: u32,
    pub propbench: String,
    pub python: String,
    pub coolprop: String,
}

#[derive(Debug, Serialize)]
pub(crate) struct Request<'a> {
    pub jsonrpc: &'static str,
    pub id: u64,
    pub method: &'a str,
    pub params: &'a Value,
}

/// Any line the worker writes: a response (has `id`) or a notification (has `method`).
#[derive(Debug, Deserialize)]
pub(crate) struct Incoming {
    pub jsonrpc: String,
    #[serde(default)]
    pub id: Option<Value>,
    #[serde(default)]
    pub method: Option<String>,
    #[serde(default)]
    pub params: Option<Value>,
    #[serde(default)]
    pub result: Option<Value>,
    #[serde(default)]
    pub error: Option<RpcErrorObject>,
}

#[derive(Debug, Deserialize)]
pub(crate) struct RpcErrorObject {
    pub code: i64,
    pub message: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_serialises_as_json_rpc_2() {
        let params = serde_json::json!({"fluid": "R134a"});
        let line = serde_json::to_string(&Request {
            jsonrpc: "2.0",
            id: 3,
            method: "property",
            params: &params,
        })
        .unwrap();
        assert_eq!(
            line,
            r#"{"jsonrpc":"2.0","id":3,"method":"property","params":{"fluid":"R134a"}}"#
        );
    }

    #[test]
    fn property_request_round_trip_keeps_values_exact() {
        let req = PropertyRequest {
            fluid: "R134a".into(),
            pair: "PT_INPUTS".into(),
            values: [1.0e6, 300.000_000_000_000_06],
            output: "Dmass".into(),
        };
        let back: PropertyRequest = serde_json::from_str(&serde_json::to_string(&req).unwrap()).unwrap();
        assert_eq!(back, req);
    }

    #[test]
    fn result_parses_full_precision() {
        let r: PropertyResult = serde_json::from_str(
            r#"{"value":1201.5290150541637,"output":"Dmass","backend":"CoolProp::HEOS","backend_version":"7.1.0"}"#,
        )
        .unwrap();
        assert_eq!(r.value, 1201.5290150541637);
    }

    #[test]
    fn incoming_distinguishes_responses_and_notifications() {
        let n: Incoming = serde_json::from_str(r#"{"jsonrpc":"2.0","method":"ready","params":{}}"#).unwrap();
        assert!(n.id.is_none());
        assert_eq!(n.method.as_deref(), Some("ready"));
        let e: Incoming =
            serde_json::from_str(r#"{"jsonrpc":"2.0","id":1,"error":{"code":-32001,"message":"x"}}"#).unwrap();
        assert_eq!(e.error.map(|e| e.code), Some(-32001));
    }
}
