use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::EngineError;

/// Environment variable that overrides which Python runs the worker (used by tests and CI).
pub const WORKER_PYTHON_ENV: &str = "PB_WORKER_PYTHON";

/// Environment variables passed through to the worker; everything else is cleared (README §4c, isolation).
const ENV_ALLOWLIST: &[&str] = &[
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "LANG",
    "LC_ALL",
    // PropBench's own settings: components folder and component registry (README §2b).
    "PB_COMPONENTS_DIR",
    "PB_ENVS_DIR",
    "PB_REGISTRY_URL",
];

/// How to start a worker process.
#[derive(Debug, Clone)]
pub struct WorkerCommand {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    /// Environment of the worker. The parent environment is cleared first.
    pub env: Vec<(OsString, OsString)>,
}

impl WorkerCommand {
    /// The `propbench` worker in isolated mode: no user site-packages, no `PYTHON*` variables, no bytecode writes.
    pub fn python_worker(python: PathBuf) -> Self {
        Self::python(python, ["-I", "-B", "-X", "utf8", "-m", "propbench.worker"])
    }

    /// Any Python invocation with the isolated environment (used for tests of the supervisor).
    pub fn python<I, S>(python: PathBuf, args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<OsString>,
    {
        let env = ENV_ALLOWLIST
            .iter()
            .filter_map(|key| std::env::var_os(key).map(|value| (OsString::from(key), value)))
            .collect();
        Self {
            program: python,
            args: args.into_iter().map(Into::into).collect(),
            env,
        }
    }
}

impl WorkerCommand {
    /// The same command with one more (or a replaced) environment variable.
    pub fn with_env(mut self, key: impl Into<OsString>, value: impl Into<OsString>) -> Self {
        let key = key.into();
        self.env.retain(|(k, _)| *k != key);
        self.env.push((key, value.into()));
        self
    }
}

/// Engine settings.
#[derive(Debug, Clone)]
pub struct EngineConfig {
    pub worker: WorkerCommand,
    /// Time allowed for the worker to send its `ready` notification.
    pub startup_timeout: Duration,
    /// Time allowed for one request; on expiry the worker is stopped and restarted on the next call.
    pub request_timeout: Duration,
    /// More than this many failures within `failure_window` puts the engine into the failed state.
    pub max_failures: usize,
    pub failure_window: Duration,
}

impl EngineConfig {
    pub fn new(worker: WorkerCommand) -> Self {
        Self {
            worker,
            startup_timeout: Duration::from_secs(60),
            request_timeout: Duration::from_secs(30),
            max_failures: 3,
            failure_window: Duration::from_secs(60),
        }
    }
}

/// Path of the interpreter inside a bundled standalone Python directory.
pub fn bundled_python(python_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        python_dir.join("python.exe")
    } else {
        python_dir.join("bin").join("python3")
    }
}

/// Find the Python that runs the worker: `PB_WORKER_PYTHON`, then the bundled Python (if a directory is given),
/// then, in debug builds only, the development environment `worker/.venv` created by `uv sync --project worker`.
pub fn resolve_worker_python(bundled_dir: Option<&Path>) -> Result<PathBuf, EngineError> {
    let mut tried = Vec::new();
    if let Some(path) = std::env::var_os(WORKER_PYTHON_ENV) {
        let path = PathBuf::from(path);
        if path.is_file() {
            return Ok(path);
        }
        return Err(EngineError::PythonNotFound(format!(
            "{WORKER_PYTHON_ENV}={} is not a file",
            path.display()
        )));
    }
    if let Some(dir) = bundled_dir {
        let path = bundled_python(dir);
        if path.is_file() {
            return Ok(path);
        }
        tried.push(path);
    }
    if cfg!(debug_assertions) {
        let venv = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../worker/.venv");
        let path = if cfg!(windows) {
            venv.join("Scripts").join("python.exe")
        } else {
            venv.join("bin").join("python")
        };
        if path.is_file() {
            return Ok(path);
        }
        tried.push(path);
    }
    let tried: Vec<String> = tried.iter().map(|p| p.display().to_string()).collect();
    Err(EngineError::PythonNotFound(format!(
        "set {WORKER_PYTHON_ENV} or run `uv sync --project worker` (tried: {})",
        tried.join(", ")
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worker_command_runs_isolated_module() {
        let cmd = WorkerCommand::python_worker(PathBuf::from("python"));
        let args: Vec<_> = cmd.args.iter().map(|a| a.to_string_lossy().into_owned()).collect();
        assert_eq!(args, ["-I", "-B", "-X", "utf8", "-m", "propbench.worker"]);
        assert!(
            cmd.env
                .iter()
                .all(|(k, _)| ENV_ALLOWLIST.contains(&k.to_string_lossy().as_ref()))
        );
    }

    #[test]
    fn bundled_python_layout() {
        let p = bundled_python(Path::new("res/python"));
        if cfg!(windows) {
            assert!(p.ends_with("python.exe"));
        } else {
            assert!(p.ends_with("bin/python3"));
        }
    }
}
