use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};

use pb_engine::store::{Project, ResultCache, StoreError, now_seconds};
use pb_engine::{Engine, EngineConfig, EngineError, Method, PropertyRequest, PropertyResult, WorkerCommand};
use pb_term::{Terminal, activated_env, activation_command, default_shell};
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, Runtime};

/// Entries kept in the result cache (least recently used ones are dropped when the app starts).
const CACHE_ENTRIES: usize = 5000;

/// The engine, created on first use with the Python bundled with the app (`<resources>/python`; see
/// `pb_engine::resolve_worker_python`), or the reason it could not be configured; and the job result cache in the
/// app data folder (`<app data>/cache/results.sqlite`), or `None` if it cannot be opened (jobs then always run).
#[derive(Default)]
pub struct AppEngine(OnceLock<Result<Engine, String>>, OnceLock<Option<ResultCache>>);

impl AppEngine {
    fn cache<R: Runtime>(&self, app: &AppHandle<R>) -> Option<&ResultCache> {
        self.1
            .get_or_init(|| {
                let path = app.path().app_data_dir().ok()?.join("cache").join("results.sqlite");
                match ResultCache::open(&path) {
                    Ok(cache) => {
                        let _ = cache.prune(CACHE_ENTRIES);
                        Some(cache)
                    }
                    Err(err) => {
                        eprintln!("[propbench] result cache unavailable: {err}");
                        None
                    }
                }
            })
            .as_ref()
    }

    fn engine<R: Runtime>(&self, app: &AppHandle<R>) -> Result<&Engine, CommandError> {
        self.0
            .get_or_init(|| {
                let bundled = app.path().resource_dir().ok().map(|dir| dir.join("python"));
                let data = app.path().app_data_dir().ok();
                pb_engine::resolve_worker_python(bundled.as_deref())
                    .map(|python| {
                        let mut worker = WorkerCommand::python_worker(python);
                        if let Some(dir) = data {
                            // components and project environments live only here (CLAUDE.md isolation rule)
                            worker = worker
                                .with_env("PB_COMPONENTS_DIR", dir.join("components"))
                                .with_env("PB_ENVS_DIR", dir.join("envs"));
                        }
                        Engine::new(EngineConfig::new(worker))
                    })
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

impl From<StoreError> for CommandError {
    fn from(err: StoreError) -> Self {
        Self {
            kind: "project",
            message: err.to_string(),
        }
    }
}

impl From<EngineError> for CommandError {
    fn from(err: EngineError) -> Self {
        let kind = match &err {
            EngineError::PythonNotFound(_) => "python_not_found",
            EngineError::Spawn { .. } | EngineError::Startup(_) => "worker_start",
            EngineError::WorkerExited(_) | EngineError::Failed { .. } => "worker_crashed",
            EngineError::Timeout(_) => "timeout",
            EngineError::Cancelled => "cancelled",
            EngineError::Protocol(_) | EngineError::Io(_) => "protocol",
            EngineError::Rpc { code, .. } if *code == EngineError::INVALID_PARAMS => "invalid_input",
            EngineError::Rpc { code, .. } if *code == EngineError::PROPBENCH_ERROR => "propbench",
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

/// One worker operation of protocol v2 (`pb_engine::Method`, e.g. `model.fit`) with JSON params. Only the methods
/// in that whitelist can be called.
#[tauri::command]
pub async fn worker<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    method: String,
    params: Option<Value>,
) -> Result<Value, CommandError> {
    let method = Method::from_name(&method).ok_or_else(|| CommandError {
        kind: "invalid_input",
        message: format!("unknown worker method `{method}`"),
    })?;
    let engine = state.engine(&app)?;
    let (result, _cached) = engine
        .invoke_cached(method, params.unwrap_or(Value::Null), state.cache(&app))
        .await?;
    Ok(result)
}

/// Stop the running worker operation (the toolbar's Stop). The next operation starts a fresh worker.
#[tauri::command]
pub async fn cancel<R: Runtime>(app: AppHandle<R>, state: tauri::State<'_, AppEngine>) -> Result<(), CommandError> {
    state.engine(&app)?.cancel().await;
    Ok(())
}

fn project_path(path: &str) -> Result<PathBuf, CommandError> {
    let path = PathBuf::from(path);
    if path.extension().and_then(|e| e.to_str()) != Some("pbp") {
        return Err(CommandError {
            kind: "invalid_input",
            message: format!("{} is not a .pbp project file", path.display()),
        });
    }
    Ok(path)
}

fn stamp<R: Runtime>(app: &AppHandle<R>, project: &mut Project) {
    project.meta.modified = now_seconds();
    project.meta.app_version = app.package_info().version.to_string();
}

/// Save the project to a `.pbp` file the user chose (atomic: temporary file + rename).
#[tauri::command]
pub async fn project_save<R: Runtime>(
    app: AppHandle<R>,
    path: String,
    mut project: Project,
) -> Result<Project, CommandError> {
    let path = project_path(&path)?;
    stamp(&app, &mut project);
    project.save(&path)?;
    if let Some(autosave) = autosave_path(&app) {
        let _ = std::fs::remove_file(autosave);
    }
    Ok(project)
}

/// Open a `.pbp` project file (older formats are migrated in memory; newer ones are refused).
#[tauri::command]
pub async fn project_open(path: String) -> Result<Project, CommandError> {
    Ok(Project::load(&project_path(&path)?)?)
}

fn autosave_path<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    Some(app.path().app_data_dir().ok()?.join("autosave").join("autosave.pbp"))
}

/// Keep a recovery copy of the open project in the app data folder (never next to the user's files).
#[tauri::command]
pub async fn project_autosave<R: Runtime>(app: AppHandle<R>, mut project: Project) -> Result<(), CommandError> {
    let Some(path) = autosave_path(&app) else {
        return Ok(());
    };
    stamp(&app, &mut project);
    project.save(&path)?;
    Ok(())
}

/// The recovery copy left by a session that did not end with a save, if any.
#[tauri::command]
pub async fn project_recover<R: Runtime>(app: AppHandle<R>) -> Result<Option<Project>, CommandError> {
    match autosave_path(&app).filter(|p| Path::is_file(p)) {
        Some(path) => Ok(Some(Project::load(&path)?)),
        None => Ok(None),
    }
}

/// Remove the recovery copy (the user declined it, or the project was saved or closed).
#[tauri::command]
pub async fn project_discard_autosave<R: Runtime>(app: AppHandle<R>) -> Result<(), CommandError> {
    if let Some(path) = autosave_path(&app) {
        let _ = std::fs::remove_file(path);
    }
    Ok(())
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
        assert_eq!(CommandError::from(EngineError::Cancelled).kind, "cancelled");
        assert_eq!(CommandError::from(StoreError::Invalid("x".into())).kind, "project");
    }

    #[test]
    fn only_pbp_files_are_project_paths() {
        assert!(project_path("/tmp/a.pbp").is_ok());
        assert_eq!(project_path("/tmp/a.txt").unwrap_err().kind, "invalid_input");
    }
}

/// Open terminals by id (README §4: terminal inside the project environment).
#[derive(Default)]
pub struct Terminals {
    open: Mutex<HashMap<u32, Arc<Terminal>>>,
    next: AtomicU32,
}

impl Terminals {
    fn get(&self, id: u32) -> Result<Arc<Terminal>, CommandError> {
        self.open
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(&id)
            .cloned()
            .ok_or_else(|| CommandError {
                kind: "invalid_input",
                message: format!("no terminal {id}"),
            })
    }
}

#[derive(Clone, Serialize)]
struct TerminalOutput {
    id: u32,
    data: Vec<u8>,
}

fn terminal_error(err: pb_term::TermError) -> CommandError {
    CommandError {
        kind: "terminal",
        message: err.to_string(),
    }
}

/// Open the user's shell in the project's environment (created if needed). Output arrives as
/// `terminal-output` events ({id, data}); `terminal-exit` ({id}) when the shell ends.
#[tauri::command]
pub async fn terminal_open<R: Runtime>(
    app: AppHandle<R>,
    engine: tauri::State<'_, AppEngine>,
    terminals: tauri::State<'_, Terminals>,
    project: String,
    cols: u16,
    rows: u16,
) -> Result<u32, CommandError> {
    let status = engine
        .engine(&app)?
        .invoke(Method::EnvCreate, serde_json::json!({ "project": project }))
        .await?;
    let field = |k: &str| status.get(k).and_then(Value::as_str).map(PathBuf::from);
    let (Some(root), Some(python)) = (field("path"), field("python")) else {
        return Err(CommandError {
            kind: "protocol",
            message: "env.create did not return the environment's paths".into(),
        });
    };
    let bin = python.parent().map_or_else(|| root.clone(), Path::to_path_buf);
    let shell = default_shell();
    let (term, rx) = Terminal::spawn(
        &shell,
        &[],
        &root,
        &activated_env(&root, &bin),
        cols.max(20),
        rows.max(5),
    )
    .map_err(terminal_error)?;
    term.write(activation_command(&shell, &root, &bin).as_bytes())
        .map_err(terminal_error)?;
    let id = terminals.next.fetch_add(1, Ordering::Relaxed) + 1;
    terminals
        .open
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .insert(id, Arc::new(term));
    std::thread::spawn(move || {
        while let Ok(data) = rx.recv() {
            if app.emit("terminal-output", TerminalOutput { id, data }).is_err() {
                break;
            }
        }
        let _ = app.emit("terminal-exit", serde_json::json!({ "id": id }));
    });
    Ok(id)
}

#[tauri::command]
pub async fn terminal_write(terminals: tauri::State<'_, Terminals>, id: u32, data: String) -> Result<(), CommandError> {
    terminals.get(id)?.write(data.as_bytes()).map_err(terminal_error)
}

#[tauri::command]
pub async fn terminal_resize(
    terminals: tauri::State<'_, Terminals>,
    id: u32,
    cols: u16,
    rows: u16,
) -> Result<(), CommandError> {
    terminals
        .get(id)?
        .resize(cols.max(20), rows.max(5))
        .map_err(terminal_error)
}

#[tauri::command]
pub async fn terminal_close(terminals: tauri::State<'_, Terminals>, id: u32) -> Result<(), CommandError> {
    if let Some(term) = terminals
        .open
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .remove(&id)
    {
        term.kill();
    }
    Ok(())
}
