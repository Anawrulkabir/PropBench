use std::sync::OnceLock;

use pb_engine::{Engine, EngineConfig, EngineError, PropertyRequest, PropertyResult, WorkerCommand};
use serde::Serialize;
use tauri::{AppHandle, Manager, Runtime};

/// The engine, created on first use with the Python bundled with the app (`<resources>/python`; see
/// `pb_engine::resolve_worker_python`), or the reason it could not be configured.
#[derive(Default)]
pub struct AppEngine(OnceLock<Result<Engine, String>>);

impl AppEngine {
    fn engine<R: Runtime>(&self, app: &AppHandle<R>) -> Result<&Engine, CommandError> {
        self.0
            .get_or_init(|| {
                let bundled = app.path().resource_dir().ok().map(|dir| dir.join("python"));
                pb_engine::resolve_worker_python(bundled.as_deref())
                    .map(|python| Engine::new(EngineConfig::new(WorkerCommand::python_worker(python))))
                    .map_err(|err| err.to_string())
            })
            .as_ref()
            .map_err(|message| CommandError {
                kind: "python_not_found",
                message: message.clone(),
            })
    }

    pub async fn shutdown(&self) {
        if let Some(Ok(engine)) = self.0.get() {
            engine.shutdown().await;
        }
    }
}

/// Error sent to the UI: a stable `kind` for code and a readable `message` for people.
#[derive(Debug, Serialize, PartialEq)]
pub struct CommandError {
    kind: &'static str,
    message: String,
}

impl From<EngineError> for CommandError {
    fn from(err: EngineError) -> Self {
        let kind = match &err {
            EngineError::PythonNotFound(_) => "python_not_found",
            EngineError::Spawn { .. } | EngineError::Startup(_) => "worker_start",
            EngineError::WorkerExited(_) | EngineError::Failed { .. } => "worker_crashed",
            EngineError::Timeout(_) => "timeout",
            EngineError::Protocol(_) | EngineError::Io(_) => "protocol",
            EngineError::Rpc { code, .. } if *code == EngineError::INVALID_PARAMS => "invalid_input",
            EngineError::Rpc { .. } => "property",
        };
        Self {
            kind,
            message: err.to_string(),
        }
    }
}

/// One property at one state, SI units (see `pb_engine::PropertyRequest`).
#[tauri::command]
pub async fn property<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    request: PropertyRequest,
) -> Result<PropertyResult, CommandError> {
    Ok(state.engine(&app)?.property(&request).await?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engine_errors_map_to_stable_kinds() {
        let rpc = |code| EngineError::Rpc {
            code,
            message: "unknown fluid 'X'".into(),
        };
        assert_eq!(
            CommandError::from(rpc(EngineError::BACKEND_ERROR)),
            CommandError {
                kind: "property",
                message: "unknown fluid 'X'".into()
            }
        );
        assert_eq!(
            CommandError::from(rpc(EngineError::INVALID_PARAMS)).kind,
            "invalid_input"
        );
        assert_eq!(
            CommandError::from(EngineError::Timeout(std::time::Duration::from_secs(1))).kind,
            "timeout"
        );
    }
}
