//! Embedded terminal (README §4, M1c): the user's shell in a pseudo-terminal (ConPTY on Windows, a pty elsewhere),
//! started inside the project environment. The environment is activated only for this shell (its `PATH` and
//! `VIRTUAL_ENV`); the user's session, the system Python and the system `PATH` are never changed.

use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use portable_pty::{Child, CommandBuilder, MasterPty, PtySize, native_pty_system};

#[derive(Debug, thiserror::Error)]
pub enum TermError {
    #[error("terminal error: {0}")]
    Pty(String),
    #[error("terminal I/O error: {0}")]
    Io(#[from] std::io::Error),
}

fn pty_err(err: impl std::fmt::Display) -> TermError {
    TermError::Pty(err.to_string())
}

/// The user's shell: `$SHELL` (or `/bin/sh`) on Unix, `%COMSPEC%` (or `cmd.exe`) on Windows.
pub fn default_shell() -> PathBuf {
    if cfg!(windows) {
        std::env::var_os("COMSPEC").map_or_else(|| PathBuf::from("cmd.exe"), PathBuf::from)
    } else {
        std::env::var_os("SHELL").map_or_else(|| PathBuf::from("/bin/sh"), PathBuf::from)
    }
}

/// Environment variables of a shell inside the environment whose executables are in `env_bin`: the current
/// environment with `env_bin` first on `PATH`, `VIRTUAL_ENV` set and Python's own variables removed.
pub fn activated_env(env_root: &Path, env_bin: &Path) -> Vec<(String, String)> {
    let mut vars: Vec<(String, String)> = std::env::vars()
        .filter(|(k, _)| {
            !matches!(
                k.to_ascii_uppercase().as_str(),
                "PYTHONHOME" | "PYTHONPATH" | "PYTHONSTARTUP"
            )
        })
        .collect();
    let path_key = vars
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case("PATH"))
        .map_or_else(|| "PATH".to_owned(), |(k, _)| k.clone());
    let old = vars.iter().find(|(k, _)| *k == path_key).map(|(_, v)| v.clone());
    let mut parts = vec![env_bin.to_path_buf()];
    if let Some(old) = old {
        parts.extend(std::env::split_paths(&old));
    }
    let joined = std::env::join_paths(parts)
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| env_bin.display().to_string());
    vars.retain(|(k, _)| *k != path_key && k != "VIRTUAL_ENV");
    vars.push((path_key, joined));
    vars.push(("VIRTUAL_ENV".into(), env_root.display().to_string()));
    vars
}

/// The line that (re)activates the environment inside a started shell: start-up files such as `.bashrc` may put
/// their own folders before ours on `PATH`, so the terminal sends this once the shell runs (as IDEs do).
pub fn activation_command(shell: &Path, env_root: &Path, env_bin: &Path) -> String {
    let name = shell
        .file_stem()
        .map(|s| s.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();
    let (root, bin) = (env_root.display(), env_bin.display());
    if name == "cmd" {
        format!("set \"VIRTUAL_ENV={root}\" & set \"PATH={bin};%PATH%\"\r\n")
    } else if name == "powershell" || name == "pwsh" {
        format!("$env:VIRTUAL_ENV = '{root}'; $env:PATH = '{bin};' + $env:PATH\r\n")
    } else {
        let quote = |p: &str| format!("'{}'", p.replace('\'', "'\\''"));
        format!(
            " export VIRTUAL_ENV={}; export PATH={}:\"$PATH\"\n",
            quote(&root.to_string()),
            quote(&bin.to_string())
        )
    }
}

/// A running shell in a pseudo-terminal. Output arrives on the receiver returned by [`Terminal::spawn`].
pub struct Terminal {
    master: Mutex<Box<dyn MasterPty + Send>>,
    writer: Mutex<Box<dyn Write + Send>>,
    child: Arc<Mutex<Box<dyn Child + Send + Sync>>>,
}

fn lock<T: ?Sized>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(PoisonError::into_inner)
}

impl Terminal {
    /// Start `program` (with `args`) in `cwd` with exactly the environment `env`.
    pub fn spawn(
        program: &Path,
        args: &[String],
        cwd: &Path,
        env: &[(String, String)],
        cols: u16,
        rows: u16,
    ) -> Result<(Self, Receiver<Vec<u8>>), TermError> {
        let pair = native_pty_system()
            .openpty(PtySize {
                rows,
                cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(pty_err)?;
        let mut cmd = CommandBuilder::new(program);
        cmd.args(args);
        cmd.cwd(cwd);
        cmd.env_clear();
        for (k, v) in env {
            cmd.env(k, v);
        }
        let child = pair.slave.spawn_command(cmd).map_err(pty_err)?;
        drop(pair.slave);
        let mut reader = pair.master.try_clone_reader().map_err(pty_err)?;
        let writer = pair.master.take_writer().map_err(pty_err)?;
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let mut buf = [0u8; 8192];
            loop {
                match reader.read(&mut buf) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => {
                        if tx.send(buf[..n].to_vec()).is_err() {
                            break;
                        }
                    }
                }
            }
        });
        Ok((
            Self {
                master: Mutex::new(pair.master),
                writer: Mutex::new(writer),
                child: Arc::new(Mutex::new(child)),
            },
            rx,
        ))
    }

    pub fn write(&self, data: &[u8]) -> Result<(), TermError> {
        let mut w = lock(&self.writer);
        w.write_all(data)?;
        w.flush()?;
        Ok(())
    }

    pub fn resize(&self, cols: u16, rows: u16) -> Result<(), TermError> {
        lock(&self.master)
            .resize(PtySize {
                rows,
                cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(pty_err)
    }

    /// Exit status if the shell has ended.
    pub fn exited(&self) -> Option<u32> {
        lock(&self.child).try_wait().ok().flatten().map(|s| s.exit_code())
    }

    pub fn kill(&self) {
        let _ = lock(&self.child).kill();
    }
}

impl Drop for Terminal {
    fn drop(&mut self) {
        self.kill();
    }
}
