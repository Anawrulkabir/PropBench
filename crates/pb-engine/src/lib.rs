//! PropBench engine (README §4b).
//!
//! The engine starts a Python worker (the `propbench` package, `python -m propbench.worker`), supervises it and
//! talks to it over JSON-RPC 2.0, one JSON message per line on stdio. All science runs in the worker; this crate
//! only moves requests and results and restarts the worker when it dies.

mod config;
mod error;
mod jobs;
mod methods;
mod rpc;
mod worker;

pub use config::{EngineConfig, RemoteTarget, WorkerCommand, bundled_python, resolve_worker_python};
pub use error::EngineError;
pub use jobs::{Job, JobEvent, JobGraph, JobOutcome, canonical_json, job_key};
pub use methods::Method;
pub use pb_store as store;
pub use rpc::{PROTOCOL_VERSION, PropertyRequest, PropertyResult, WorkerInfo};
pub use worker::Engine;
