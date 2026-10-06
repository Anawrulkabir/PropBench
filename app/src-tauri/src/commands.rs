use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};

use pb_engine::store::{Project, ResultCache, StoreError, now_seconds};
use pb_engine::{
    Engine, EngineConfig, EngineError, Method, PropertyRequest, PropertyResult, RemoteTarget, WorkerCommand, WorkerInfo,
};
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

/// The remote engine (README §4d), when connected: a worker on another machine over the user's SSH.
#[derive(Default)]
pub struct RemoteEngine(tokio::sync::Mutex<Option<(RemoteTarget, Arc<Engine>)>>);

/// Operations that may run on the remote engine: computations on data sent with the request. Everything that
/// touches this computer's files (components, environments, scripts) stays local.
fn remote_capable(method: Method) -> bool {
    matches!(
        method,
        Method::ModelFit
            | Method::StudyValidate
            | Method::ConsistencyAnalyze
            | Method::ModelCompare
            | Method::ModelPredict
            | Method::CurveFit
            | Method::GumMonteCarlo
    )
}

/// Connect to a remote engine and return the versions it reports (same protocol required).
#[tauri::command]
pub async fn remote_connect(
    remote: tauri::State<'_, RemoteEngine>,
    target: RemoteTarget,
) -> Result<WorkerInfo, CommandError> {
    let command = WorkerCommand::ssh(&target, &["ssh".into()])?;
    let engine = Arc::new(Engine::new(EngineConfig::new(command)));
    let info = engine.start().await?;
    let old = remote.0.lock().await.replace((target, engine));
    if let Some((_, old)) = old {
        old.shutdown().await;
    }
    Ok(info)
}

#[tauri::command]
pub async fn remote_disconnect(remote: tauri::State<'_, RemoteEngine>) -> Result<(), CommandError> {
    if let Some((_, engine)) = remote.0.lock().await.take() {
        engine.shutdown().await;
    }
    Ok(())
}

/// One worker operation of protocol v2 (`pb_engine::Method`, e.g. `model.fit`) with JSON params. Only the methods
/// in that whitelist can be called. With `target: "remote"` a computation runs on the connected remote engine.
#[tauri::command]
pub async fn worker<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    remote: tauri::State<'_, RemoteEngine>,
    method: String,
    params: Option<Value>,
    target: Option<String>,
) -> Result<Value, CommandError> {
    let method = Method::from_name(&method).ok_or_else(|| CommandError {
        kind: "invalid_input",
        message: format!("unknown worker method `{method}`"),
    })?;
    if method.shell_only() {
        return Err(CommandError {
            kind: "invalid_input",
            message: format!(
                "`{}` needs checks of the shell (keychain, plug-in approval): use its own command",
                method.name()
            ),
        });
    }
    if target.as_deref() == Some("remote") && remote_capable(method) {
        let engine = remote
            .0
            .lock()
            .await
            .as_ref()
            .map(|(_, e)| Arc::clone(e))
            .ok_or_else(|| CommandError {
                kind: "worker_start",
                message: "no remote engine connected (Settings › Remote compute)".into(),
            })?;
        return Ok(engine.invoke(method, params.unwrap_or(Value::Null)).await?);
    }
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

// --- credentials (OS keychain), AI assistant, GitHub and project history (README §4d) ---

fn secret_name(name: &str) -> Result<&str, CommandError> {
    if name.starts_with("ai.") || name.starts_with("github.") {
        Ok(name)
    } else {
        Err(CommandError {
            kind: "invalid_input",
            message: format!("`{name}` is not a PropBench credential"),
        })
    }
}

fn secret_error(err: pb_secrets::SecretError) -> CommandError {
    CommandError {
        kind: "keychain",
        message: err.to_string(),
    }
}

/// Store a credential in the OS keychain. There is no command to read one back: keys never reach the UI.
#[tauri::command]
pub async fn secret_set(name: String, value: String) -> Result<(), CommandError> {
    pb_secrets::set(secret_name(&name)?, value.trim()).map_err(secret_error)
}

#[tauri::command]
pub async fn secret_has(name: String) -> Result<bool, CommandError> {
    pb_secrets::has(secret_name(&name)?).map_err(secret_error)
}

#[tauri::command]
pub async fn secret_delete(name: String) -> Result<(), CommandError> {
    pb_secrets::delete(secret_name(&name)?).map_err(secret_error)
}

/// Ask the AI assistant; the key of `provider` is taken from the keychain for this request only.
#[tauri::command]
pub async fn assistant_ask<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    provider: String,
    model: String,
    base_url: Option<String>,
    messages: Value,
    context: String,
) -> Result<Value, CommandError> {
    let key = pb_secrets::get(&format!("ai.{provider}")).map_err(secret_error)?;
    let params = serde_json::json!({
        "provider": provider, "model": model, "base_url": base_url, "messages": messages,
        "context": context, "api_key": key,
    });
    Ok(state.engine(&app)?.invoke(Method::AssistantAsk, params).await?)
}

/// Start GitHub's device flow with the OAuth app's client id; the UI shows the code to enter on github.com.
#[tauri::command]
pub async fn github_signin_start<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    client_id: String,
) -> Result<Value, CommandError> {
    Ok(state
        .engine(&app)?
        .invoke(Method::GithubDeviceStart, serde_json::json!({ "client_id": client_id }))
        .await?)
}

/// Poll the device flow; on success the token goes straight to the keychain (`github.token`).
#[tauri::command]
pub async fn github_signin_poll<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    client_id: String,
    device_code: String,
) -> Result<String, CommandError> {
    let res = state
        .engine(&app)?
        .invoke(
            Method::GithubDevicePoll,
            serde_json::json!({ "client_id": client_id, "device_code": device_code }),
        )
        .await?;
    let status = res
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("pending")
        .to_owned();
    if let Some(token) = res.get("token").and_then(Value::as_str) {
        pb_secrets::set("github.token", token).map_err(secret_error)?;
    }
    Ok(status)
}

/// Push the project's Git mirror to `owner/repo` on `branch` with the token from the keychain.
#[tauri::command]
pub async fn github_push<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    owner: String,
    repo: String,
    branch: String,
    message: String,
    project: Project,
) -> Result<Value, CommandError> {
    let token = pb_secrets::get("github.token")
        .map_err(secret_error)?
        .ok_or_else(|| CommandError {
            kind: "keychain",
            message: "sign in to GitHub first (Settings › GitHub)".into(),
        })?;
    let files: serde_json::Map<String, Value> = pb_git::mirror_files(&project)
        .map_err(git_error)?
        .into_iter()
        .map(|(k, v)| (k, Value::String(String::from_utf8_lossy(&v).into_owned())))
        .collect();
    let params = serde_json::json!({
        "token": token, "owner": owner, "repo": repo, "branch": branch, "files": files, "message": message,
    });
    Ok(state.engine(&app)?.invoke(Method::GithubPush, params).await?)
}

fn git_error(err: pb_git::GitError) -> CommandError {
    CommandError {
        kind: "git",
        message: err.to_string(),
    }
}

/// Folder of a project's Git history: next to a saved project (`<name>.history`), else in the app data folder.
fn history_dir<R: Runtime>(app: &AppHandle<R>, path: Option<&str>, name: &str) -> Option<PathBuf> {
    match path {
        Some(p) => {
            let p = PathBuf::from(p);
            let stem = p.file_stem()?.to_string_lossy().into_owned();
            Some(p.with_file_name(format!("{stem}.history")))
        }
        None => {
            let slug: String = name
                .chars()
                .map(|c| {
                    if c.is_ascii_alphanumeric() {
                        c.to_ascii_lowercase()
                    } else {
                        '-'
                    }
                })
                .collect();
            Some(app.path().app_data_dir().ok()?.join("history").join(slug))
        }
    }
}

/// Commit the project's mirror to its history; `None` when nothing changed since the last commit.
#[tauri::command]
pub async fn history_commit<R: Runtime>(
    app: AppHandle<R>,
    path: Option<String>,
    message: String,
    project: Project,
) -> Result<Option<pb_git::CommitInfo>, CommandError> {
    let dir = history_dir(&app, path.as_deref(), &project.meta.name).ok_or_else(|| CommandError {
        kind: "git",
        message: "no folder for the history".into(),
    })?;
    pb_git::commit(&dir, &project, &message, "PropBench user", "propbench@localhost").map_err(git_error)
}

#[tauri::command]
pub async fn history_list<R: Runtime>(
    app: AppHandle<R>,
    path: Option<String>,
    name: String,
) -> Result<Vec<pb_git::CommitInfo>, CommandError> {
    let Some(dir) = history_dir(&app, path.as_deref(), &name) else {
        return Ok(Vec::new());
    };
    pb_git::history(&dir, 200).map_err(git_error)
}

// --- plug-ins (README §2f): installed in `<app data>/plugins`, run only after the user approved their permissions ---

fn plugin_error(err: pb_plugin::PluginError) -> CommandError {
    CommandError {
        kind: "plugin",
        message: err.to_string(),
    }
}

fn plugin_host<R: Runtime>(app: &AppHandle<R>) -> Result<pb_plugin::PluginHost, CommandError> {
    let dir = app.path().app_data_dir().map_err(|e| CommandError {
        kind: "plugin",
        message: format!("no app data folder: {e}"),
    })?;
    Ok(pb_plugin::PluginHost::new(dir.join("plugins")))
}

/// What the install dialog shows: id, version, digest, signer and the permissions in words.
#[derive(Serialize)]
pub struct PluginPackage {
    id: String,
    name: String,
    version: String,
    runtime: pb_plugin::Runtime,
    kind: pb_plugin::Kind,
    digest: String,
    signer: pb_plugin::Signer,
    permissions: Vec<String>,
    reference: String,
}

impl From<pb_plugin::Package> for PluginPackage {
    fn from(p: pb_plugin::Package) -> Self {
        PluginPackage {
            permissions: p.manifest.permissions.describe(),
            id: p.manifest.id,
            name: p.manifest.name,
            version: p.manifest.version,
            runtime: p.manifest.runtime,
            kind: p.manifest.kind,
            digest: p.digest,
            signer: p.signer,
            reference: p.manifest.reference,
        }
    }
}

#[tauri::command]
pub async fn plugin_list<R: Runtime>(app: AppHandle<R>) -> Result<Vec<pb_plugin::Installed>, CommandError> {
    plugin_host(&app)?.list().map_err(plugin_error)
}

/// Verify a plug-in folder (from a file dialog, or a plug-in component installed from the registry) and copy it
/// into the plug-ins folder. It does not run until `plugin_approve`.
#[tauri::command]
pub async fn plugin_install<R: Runtime>(app: AppHandle<R>, dir: String) -> Result<PluginPackage, CommandError> {
    Ok(plugin_host(&app)?
        .install(Path::new(&dir))
        .map_err(plugin_error)?
        .into())
}

/// Install a plug-in component installed by the components manager (`<components>/<id>/<version>/plugin`).
#[tauri::command]
pub async fn plugin_install_component<R: Runtime>(
    app: AppHandle<R>,
    id: String,
    version: String,
) -> Result<PluginPackage, CommandError> {
    let bad = |what: &str| what.is_empty() || what.contains(['/', '\\']) || what.starts_with('.');
    if bad(&id) || bad(&version) {
        return Err(CommandError {
            kind: "invalid_input",
            message: "invalid component".into(),
        });
    }
    let base = app.path().app_data_dir().map_err(|e| CommandError {
        kind: "plugin",
        message: e.to_string(),
    })?;
    let dir = base.join("components").join(&id).join(&version).join("plugin");
    Ok(plugin_host(&app)?.install(&dir).map_err(plugin_error)?.into())
}

/// The user's approval of exactly the package (digest) and permissions shown in the dialog.
#[tauri::command]
pub async fn plugin_approve<R: Runtime>(
    app: AppHandle<R>,
    id: String,
    digest: String,
    allow_unsigned: bool,
) -> Result<pb_plugin::Approval, CommandError> {
    plugin_host(&app)?
        .approve(&id, &digest, allow_unsigned)
        .map_err(plugin_error)
}

#[tauri::command]
pub async fn plugin_revoke<R: Runtime>(app: AppHandle<R>, id: String) -> Result<(), CommandError> {
    plugin_host(&app)?.revoke(&id).map_err(plugin_error)
}

#[tauri::command]
pub async fn plugin_remove<R: Runtime>(app: AppHandle<R>, id: String) -> Result<(), CommandError> {
    plugin_host(&app)?.remove(&id).map_err(plugin_error)
}

/// Trust a plug-in author's minisign public key; returns its key id.
#[tauri::command]
pub async fn plugin_trust<R: Runtime>(app: AppHandle<R>, key: String) -> Result<String, CommandError> {
    plugin_host(&app)?.trust_key(&key).map_err(plugin_error)
}

/// Evaluate a model plug-in at (T in K, molar density in mol/m³) states: WASM here, Python in the project
/// environment through the worker.
#[tauri::command]
pub async fn plugin_predict<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    id: String,
    temperature: Vec<f64>,
    molar_density: Vec<f64>,
    environment: String,
) -> Result<Vec<f64>, CommandError> {
    let host = plugin_host(&app)?;
    let (pkg, _) = host.load(&id).map_err(plugin_error)?;
    if pkg.manifest.runtime == pb_plugin::Runtime::Wasm {
        let states: Vec<(f64, f64)> = temperature.into_iter().zip(molar_density).collect();
        return host.predict(&id, &states).map_err(plugin_error);
    }
    let params = serde_json::json!({ "temperature": temperature, "molar_density": molar_density });
    let out = plugin_python(app, state, id, "predict".into(), params, environment, None).await?;
    serde_json::from_value(out["result"]["values"].clone()).map_err(|e| CommandError {
        kind: "plugin",
        message: format!("plug-in returned no values: {e}"),
    })
}

/// Check-value harness of an installed, approved plug-in ("verified" mark).
#[tauri::command]
pub async fn plugin_check<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    id: String,
    environment: String,
) -> Result<Value, CommandError> {
    let host = plugin_host(&app)?;
    let (pkg, _) = host.load(&id).map_err(plugin_error)?;
    if pkg.manifest.runtime == pb_plugin::Runtime::Wasm {
        let results = host.check(&pkg.dir).map_err(plugin_error)?;
        let verified = !results.is_empty() && results.iter().all(|r| r.pass);
        return Ok(serde_json::json!({ "results": results, "verified": verified }));
    }
    let out = plugin_python(app, state, id, "check".into(), Value::Null, environment, None).await?;
    Ok(out["result"].clone())
}

/// Run an approved Python plug-in in the project environment with its approved permissions (and its declared
/// folders of the project folder `project_dir`).
#[tauri::command]
pub async fn plugin_python<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppEngine>,
    id: String,
    method: String,
    params: Value,
    environment: String,
    project_dir: Option<String>,
) -> Result<Value, CommandError> {
    let request = plugin_host(&app)?
        .python_request(&id, project_dir.as_deref().map(Path::new), &method, params)
        .map_err(plugin_error)?;
    let params = serde_json::json!({ "request": request, "project": environment });
    Ok(state.engine(&app)?.invoke(Method::PluginsRun, params).await?)
}

/// Run an approved WASM tool plug-in with `input` on its standard input and its declared folders of `project_dir`.
#[tauri::command]
pub async fn plugin_run<R: Runtime>(
    app: AppHandle<R>,
    id: String,
    input: String,
    project_dir: Option<String>,
) -> Result<pb_plugin::wasm::Output, CommandError> {
    let host = plugin_host(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        host.run(&id, project_dir.as_deref().map(Path::new), input.as_bytes(), &[])
    })
    .await
    .map_err(|e| CommandError {
        kind: "plugin",
        message: e.to_string(),
    })?
    .map_err(plugin_error)
}
