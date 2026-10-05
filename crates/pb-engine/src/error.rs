use std::time::Duration;

/// Everything that can go wrong between the engine and a worker.
#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("worker Python not found: {0}")]
    PythonNotFound(String),
    #[error("failed to start worker `{program}`: {source}")]
    Spawn {
        program: String,
        #[source]
        source: std::io::Error,
    },
    #[error("worker did not start: {0}")]
    Startup(String),
    #[error("worker exited unexpectedly{0}")]
    WorkerExited(String),
    #[error("worker did not answer within {0:?}; it was stopped and will be restarted")]
    Timeout(Duration),
    #[error("worker protocol error: {0}")]
    Protocol(String),
    #[error("worker failed {failures} times within {window:?}; not restarting")]
    Failed { failures: usize, window: Duration },
    /// An error answered by the worker itself (JSON-RPC error object), e.g. an unknown fluid.
    #[error("{message}")]
    Rpc { code: i64, message: String },
    #[error("I/O error while talking to the worker: {0}")]
    Io(#[from] std::io::Error),
}

impl EngineError {
    /// JSON-RPC error code of the worker: invalid parameters.
    pub const INVALID_PARAMS: i64 = -32602;
    /// JSON-RPC error code of the worker: the backend could not compute the property.
    pub const BACKEND_ERROR: i64 = -32001;
    /// JSON-RPC error code of the worker: bad data, model, file or fit (a PropBench domain error).
    pub const PROPBENCH_ERROR: i64 = -32002;
}
