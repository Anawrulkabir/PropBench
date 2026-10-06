//! WebAssembly runtime (wasmtime, WASI preview 1): a plug-in sees only what its manifest declares.
//!
//! * Files: each declared project folder is pre-opened under its own name (`read` read-only, `write` read-write);
//!   nothing else exists for the plug-in: no other folder, no environment variables, no network.
//! * Limits: linear memory at most `memory_mb`; execution stops after `time_s` (epoch interruption).
//! * ABI 1: a model plug-in exports `pb_predict(temperature_K: f64, molar_density: f64) -> f64` (SI); a tool
//!   plug-in is a WASI command (`_start`) that reads its request on stdin and writes its answer to stdout.

use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use serde::Serialize;
use wasmtime::{Config, Engine, Linker, Module, Store, StoreLimits, StoreLimitsBuilder};
use wasmtime_wasi::p1::{self, WasiP1Ctx};
use wasmtime_wasi::p2::pipe::{MemoryInputPipe, MemoryOutputPipe};
use wasmtime_wasi::{FsPerms, I32Exit, WasiCtxBuilder};

use crate::PluginError;
use crate::manifest::Permissions;

const TICK: Duration = Duration::from_millis(10);
const MAX_OUTPUT: usize = 16 * 1024 * 1024;

struct State {
    wasi: WasiP1Ctx,
    limits: StoreLimits,
}

/// What a tool plug-in printed and its exit code.
#[derive(Debug, Clone, Serialize)]
pub struct Output {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
}

fn wasm_err(e: impl std::fmt::Display) -> PluginError {
    PluginError::Wasm(e.to_string())
}

/// Runs the module with the store set up from `permissions`; stops it when `time_s` is exceeded.
fn with_store<R>(
    wasm: &[u8],
    permissions: &Permissions,
    project: Option<&Path>,
    stdin: &[u8],
    args: &[String],
    run: impl FnOnce(&mut Store<State>, &wasmtime::Instance) -> Result<R, PluginError>,
) -> Result<(R, MemoryOutputPipe, MemoryOutputPipe), PluginError> {
    let mut config = Config::new();
    config.epoch_interruption(true);
    let engine = Engine::new(&config).map_err(wasm_err)?;
    let module = Module::new(&engine, wasm).map_err(|e| PluginError::Wasm(format!("invalid module: {e}")))?;

    let stdout = MemoryOutputPipe::new(MAX_OUTPUT);
    let stderr = MemoryOutputPipe::new(MAX_OUTPUT);
    let mut wasi = WasiCtxBuilder::new();
    wasi.stdin(MemoryInputPipe::new(stdin.to_vec()))
        .stdout(stdout.clone())
        .stderr(stderr.clone());
    wasi.args(&[String::from("plugin")]).args(args);
    if !permissions.read.is_empty() || !permissions.write.is_empty() {
        let project = project.ok_or_else(|| PluginError::Permission("the plug-in needs a project folder".into()))?;
        for (folders, perms) in [
            (&permissions.read, FsPerms::ReadOnly),
            (&permissions.write, FsPerms::ReadWrite),
        ] {
            for f in folders {
                let host = project.join(f);
                if perms == FsPerms::ReadWrite {
                    std::fs::create_dir_all(&host).map_err(|e| PluginError::io(&host, e))?;
                }
                if host.is_dir() {
                    wasi.preopened_dir(&host, f, perms).map_err(wasm_err)?;
                }
            }
        }
    }
    let limits = StoreLimitsBuilder::new()
        .memory_size(usize::try_from(permissions.memory_mb.saturating_mul(1024 * 1024)).unwrap_or(usize::MAX))
        .instances(1)
        .build();
    let mut store = Store::new(
        &engine,
        State {
            wasi: wasi.build_p1(),
            limits,
        },
    );
    store.limiter(|s| &mut s.limits);
    let ticks = (permissions.time_s / TICK.as_secs_f64()).ceil().max(1.0) as u64;
    store.set_epoch_deadline(ticks);
    store.epoch_deadline_trap();

    let mut linker: Linker<State> = Linker::new(&engine);
    p1::add_to_linker_sync(&mut linker, |s| &mut s.wasi).map_err(wasm_err)?;

    let done = Arc::new(AtomicBool::new(false));
    let ticker = {
        let (engine, done) = (engine.clone(), done.clone());
        std::thread::spawn(move || {
            while !done.load(Ordering::Relaxed) {
                std::thread::sleep(TICK);
                engine.increment_epoch();
            }
        })
    };
    let result = linker
        .instantiate(&mut store, &module)
        .map_err(|e| limit_error(e, permissions))
        .and_then(|instance| run(&mut store, &instance));
    done.store(true, Ordering::Relaxed);
    let _ = ticker.join();
    Ok((result?, stdout, stderr))
}

fn limit_error(e: wasmtime::Error, permissions: &Permissions) -> PluginError {
    if let Some(wasmtime::Trap::Interrupt) = e.downcast_ref::<wasmtime::Trap>() {
        return PluginError::Limit(format!("stopped at the time limit of {} s", permissions.time_s));
    }
    let text = format!("{e:#}");
    if text.contains("memory") && text.contains("limit") || text.contains("resource limit") {
        return PluginError::Limit(format!("stopped at the memory limit of {} MB", permissions.memory_mb));
    }
    PluginError::Wasm(text)
}

/// Evaluate a model plug-in at the given states (temperature K, molar density mol/m³).
pub fn predict(wasm: &[u8], permissions: &Permissions, states: &[(f64, f64)]) -> Result<Vec<f64>, PluginError> {
    let (values, _, _) = with_store(wasm, permissions, None, &[], &[], |store, instance| {
        let f = instance
            .get_typed_func::<(f64, f64), f64>(&mut *store, "pb_predict")
            .map_err(|_| PluginError::Wasm("a model plug-in must export pb_predict(f64, f64) -> f64".into()))?;
        states
            .iter()
            .map(|&(t, rho)| f.call(&mut *store, (t, rho)).map_err(|e| limit_error(e, permissions)))
            .collect::<Result<Vec<_>, _>>()
    })?;
    Ok(values)
}

/// Run a tool plug-in (WASI command) with `stdin`, its declared folders of `project` and `args`.
pub fn run(
    wasm: &[u8],
    permissions: &Permissions,
    project: Option<&Path>,
    stdin: &[u8],
    args: &[String],
) -> Result<Output, PluginError> {
    let (exit_code, stdout, stderr) = with_store(wasm, permissions, project, stdin, args, |store, instance| {
        let start = instance
            .get_typed_func::<(), ()>(&mut *store, "_start")
            .map_err(|_| PluginError::Wasm("a tool plug-in must be a WASI command (export _start)".into()))?;
        match start.call(&mut *store, ()) {
            Ok(()) => Ok(0),
            Err(e) => match e.downcast_ref::<I32Exit>() {
                Some(exit) => Ok(exit.0),
                None => Err(limit_error(e, permissions)),
            },
        }
    })?;
    Ok(Output {
        stdout: String::from_utf8_lossy(&stdout.contents()).into_owned(),
        stderr: String::from_utf8_lossy(&stderr.contents()).into_owned(),
        exit_code,
    })
}
