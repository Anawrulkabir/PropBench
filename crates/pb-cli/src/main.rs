//! `propbench` command line. Every GUI action is available here (CLAUDE.md rule 2).

use std::path::{Path, PathBuf};
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use pb_engine::{Engine, EngineConfig, EngineError, Method, PropertyRequest, WorkerCommand, resolve_worker_python};
use serde_json::{Value, json};

#[derive(Parser)]
#[command(
    name = "propbench",
    version,
    about = "PropBench: thermophysical property models of new fluids"
)]
struct Cli {
    /// Python interpreter that runs the worker (default: $PB_WORKER_PYTHON, then the development environment).
    #[arg(long, global = true)]
    python: Option<PathBuf>,
    /// Folder of installed components (default: $PB_COMPONENTS_DIR).
    #[arg(long, global = true)]
    components_dir: Option<PathBuf>,
    /// Folder of project environments (default: $PB_ENVS_DIR).
    #[arg(long, global = true)]
    envs_dir: Option<PathBuf>,
    /// Write the JSON result to this file instead of standard output.
    #[arg(long, short, global = true)]
    output_file: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Compute one property at one state, SI units (CoolProp HEOS). Prints JSON.
    ///
    /// Example: propbench property --fluid R134a --pair PT_INPUTS --values 1e6,300 --output Dmass
    Property {
        /// Fluid name, e.g. R134a.
        #[arg(long)]
        fluid: String,
        /// CoolProp input pair, e.g. PT_INPUTS (pressure, then temperature).
        #[arg(long)]
        pair: String,
        /// The two input values in SI units, in the pair's order, separated by a comma.
        #[arg(long, value_delimiter = ',', required = true, allow_negative_numbers = true)]
        values: Vec<f64>,
        /// CoolProp output parameter, e.g. Dmass.
        #[arg(long)]
        output: String,
    },
    /// List the fluids of the property library.
    Fluids,
    /// Import a CSV/Excel file with a column mapping (JSON), or a ThermoML file. Prints `{datasets, warnings}`.
    Import {
        file: PathBuf,
        /// Column mapping (an import-mapping JSON file); not needed for ThermoML.
        #[arg(long)]
        mapping: Option<PathBuf>,
        /// Fluid of the data; not needed for ThermoML.
        #[arg(long)]
        fluid: Option<String>,
        /// Dataset name (default: the file name).
        #[arg(long)]
        name: Option<String>,
    },
    /// Check datasets: phases from the equation of state and disagreements with the source.
    Check {
        /// Datasets: a JSON list, or the output of `import`.
        #[arg(long)]
        data: PathBuf,
    },
    /// Starting model of a kind (ecs_viscosity, chung_viscosity, lj_dilute_viscosity) for a fluid.
    Model {
        #[arg(long)]
        kind: String,
        #[arg(long)]
        fluid: String,
        #[arg(long)]
        reference_fluid: Option<String>,
    },
    /// Fit a model to datasets. Options: {"weighted", "scale_factors", "multistart", "seed", "fixed": {name: bool}}.
    Fit {
        /// Model spec JSON (from `model`, or the `model` of a previous fit).
        #[arg(long)]
        model: PathBuf,
        #[arg(long)]
        data: PathBuf,
        /// Fit options as JSON.
        #[arg(long)]
        options: Option<String>,
    },
    /// Cross-validate a model (lostate = leave one state out, loso = leave one source out, loto, kfold, bootstrap) and run the physics checks.
    Validate {
        #[arg(long)]
        model: PathBuf,
        #[arg(long)]
        data: PathBuf,
        #[arg(long, value_delimiter = ',', default_value = "loso")]
        methods: Vec<String>,
        #[arg(long)]
        options: Option<String>,
        #[arg(long, default_value_t = 5)]
        k: u32,
        #[arg(long, default_value_t = 50)]
        n_bootstrap: u32,
        #[arg(long, default_value_t = 0)]
        seed: u64,
        /// Worker processes for the folds.
        #[arg(long, default_value_t = 1)]
        workers: u32,
    },
    /// Consistency of datasets: overlaps, model-free checks at equal T, offsets, z-scores (against reference
    /// models and the given model specs).
    Consistency {
        #[arg(long)]
        data: PathBuf,
        /// Model spec files to compare with, each as NAME=FILE (repeatable).
        #[arg(long = "model")]
        models: Vec<String>,
        /// Leave out the reference models (published registry, CoolProp correlations).
        #[arg(long)]
        no_references: bool,
        /// Isotherm tolerance in K.
        #[arg(long, default_value_t = 1.0)]
        t_tol: f64,
    },
    /// Deviation statistics of models (reference models and the given model specs) on every dataset.
    Compare {
        #[arg(long)]
        data: PathBuf,
        /// Model spec files, each as NAME=FILE (repeatable).
        #[arg(long = "model")]
        models: Vec<String>,
        #[arg(long)]
        no_references: bool,
    },
    /// Render a publication figure from a figure spec (JSON, see propbench.figures) to a file.
    Figure {
        spec: PathBuf,
        /// Output file; the format follows its extension (svg, pdf, eps, png, tiff).
        #[arg(long)]
        out: PathBuf,
        #[arg(long, default_value_t = 600)]
        dpi: u32,
    },
    /// Write a report (pdf, docx, md, or zip bundle by the extension of --out) from a report spec (JSON).
    Report {
        spec: PathBuf,
        #[arg(long)]
        out: PathBuf,
    },
    /// Export a fitted model to a CoolProp fluid file, verified inside CoolProp (at the datasets' states if given).
    ExportCoolprop {
        model: PathBuf,
        #[arg(long)]
        out: PathBuf,
        #[arg(long)]
        name: Option<String>,
        #[arg(long)]
        data: Option<PathBuf>,
    },
    /// Components: list (registry and installed), install by id or from an archive file, remove.
    Components {
        #[command(subcommand)]
        action: ComponentsAction,
    },
    /// Project environments: status, create, install packages, sync from a lock, run a script with limits.
    Env {
        #[command(subcommand)]
        action: EnvAction,
    },
    /// Project files (.pbp): create, inspect, add datasets, snapshot, export to and import from JSON.
    Project {
        #[command(subcommand)]
        action: ProjectAction,
    },
    /// Any worker operation by name with JSON params, e.g. `call selection.lock '{"rule": {...}}'`.
    Call {
        method: String,
        #[arg(default_value = "{}")]
        params: String,
    },
}

#[derive(Subcommand)]
enum ComponentsAction {
    /// Installed components, the registry's components and updates.
    List {
        /// Registry URL or path (default: $PB_REGISTRY_URL, then the PropBench registry).
        #[arg(long)]
        registry: Option<String>,
    },
    /// Download, verify and install a component (and what it requires).
    Install {
        id: String,
        #[arg(long)]
        registry: Option<String>,
    },
    /// Install a component archive without network (offline installer).
    InstallFile {
        archive: PathBuf,
    },
    Remove {
        id: String,
    },
}

#[derive(Subcommand)]
enum EnvAction {
    Status {
        project: String,
    },
    Create {
        project: String,
    },
    Install {
        project: String,
        packages: Vec<String>,
    },
    /// Make the environment match a lock file (`name==version` lines).
    Sync {
        project: String,
        lock: PathBuf,
    },
    /// Run a Python script in the environment (separate process, time and memory limits).
    Run {
        project: String,
        script: PathBuf,
        #[arg(long, default_value_t = 600.0)]
        timeout: f64,
        #[arg(long, default_value_t = 4096)]
        memory_mb: u64,
    },
}

#[derive(Subcommand)]
enum ProjectAction {
    /// Create an empty project file.
    New {
        file: PathBuf,
        #[arg(long, default_value = "Untitled project")]
        name: String,
    },
    /// Name, dates, datasets, documents, snapshots and the audit log, as JSON.
    Info { file: PathBuf },
    /// Add datasets (a JSON list, or the output of `import`) to a project.
    AddDatasets {
        file: PathBuf,
        #[arg(long)]
        data: PathBuf,
    },
    /// Store the current datasets and documents as a named snapshot.
    Snapshot {
        file: PathBuf,
        #[arg(long)]
        label: String,
    },
    /// The whole project as JSON (the same content the app saves).
    Export { file: PathBuf },
    /// Write a project file from JSON produced by `export` (atomic).
    Import { json: PathBuf, file: PathBuf },
}

fn store_error(err: pb_engine::store::StoreError) -> EngineError {
    invalid(err.to_string())
}

fn project_action(action: ProjectAction) -> Result<Value, EngineError> {
    use pb_engine::store::{DatasetRecord, Project, now_seconds};
    let save = |mut project: Project, file: &Path| -> Result<Project, EngineError> {
        project.meta.modified = now_seconds();
        project.meta.app_version = env!("CARGO_PKG_VERSION").into();
        project.save(file).map_err(store_error)?;
        Ok(project)
    };
    let to_json = |v: &Project| serde_json::to_value(v).map_err(|e| EngineError::Protocol(e.to_string()));
    match action {
        ProjectAction::New { file, name } => {
            let mut project = Project::new(&name);
            project.log("create", &name);
            let project = save(project, &file)?;
            Ok(json!({"created": path_string(&file)?, "meta": to_json(&project)?["meta"]}))
        }
        ProjectAction::Info { file } => {
            let p = Project::load(&file).map_err(store_error)?;
            let datasets: Vec<Value> = p
                .datasets
                .iter()
                .map(|d| {
                    let n = d.data.get("values").and_then(Value::as_array).map_or(0, Vec::len);
                    json!({"name": d.name, "fluid": d.data.get("fluid"), "quantity": d.data.get("quantity"), "points": n})
                })
                .collect();
            let snapshots: Vec<Value> = p
                .snapshots
                .iter()
                .map(|s| json!({"id": s.id, "label": s.label, "created": s.created}))
                .collect();
            Ok(json!({
                "meta": to_json(&p)?["meta"], "datasets": datasets,
                "documents": p.documents.keys().collect::<Vec<_>>(), "snapshots": snapshots, "audit": p.audit,
            }))
        }
        ProjectAction::AddDatasets { file, data } => {
            let mut p = Project::load(&file).map_err(store_error)?;
            let Value::Array(list) = read_datasets(&data)? else {
                return Err(invalid("expected a list of datasets"));
            };
            let mut added = Vec::new();
            for d in list {
                let name = d
                    .get("name")
                    .and_then(Value::as_str)
                    .ok_or_else(|| invalid("a dataset has no name"))?
                    .to_owned();
                p.datasets.retain(|x| x.name != name);
                p.datasets.push(DatasetRecord {
                    name: name.clone(),
                    data: d,
                });
                added.push(name);
            }
            p.log("import", &added.join(", "));
            save(p, &file)?;
            Ok(json!({"added": added}))
        }
        ProjectAction::Snapshot { file, label } => {
            let mut p = Project::load(&file).map_err(store_error)?;
            let id = p.snapshot(&label);
            save(p, &file)?;
            Ok(json!({"snapshot": id, "label": label}))
        }
        ProjectAction::Export { file } => to_json(&Project::load(&file).map_err(store_error)?),
        ProjectAction::Import { json: source, file } => {
            let project: Project = serde_json::from_value(read_json(&source)?)
                .map_err(|e| invalid(format!("{}: not a project: {e}", source.display())))?;
            save(project, &file)?;
            Ok(json!({"written": path_string(&file)?}))
        }
    }
}

/// Standard base64 (RFC 4648) of `bytes`, to send a file to the worker inside JSON.
fn base64(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
        let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(char::from(TABLE[((n >> (18 - 6 * i)) & 63) as usize]));
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// Write the `content_base64` of a worker result to `out`.
fn write_content(result: &Value, out: &Path) -> Result<Value, EngineError> {
    let content = result
        .get("content_base64")
        .and_then(Value::as_str)
        .ok_or_else(|| EngineError::Protocol("the worker returned no content".into()))?;
    let bytes = base64_decode(content).ok_or_else(|| EngineError::Protocol("content is not base64".into()))?;
    std::fs::write(out, &bytes)?;
    Ok(json!({ "written": path_string(out)?, "bytes": bytes.len(), "format": result.get("format") }))
}

/// Decode standard base64 (with padding); `None` for invalid input.
fn base64_decode(text: &str) -> Option<Vec<u8>> {
    let value = |c: u8| -> Option<u32> {
        match c {
            b'A'..=b'Z' => Some(u32::from(c - b'A')),
            b'a'..=b'z' => Some(u32::from(c - b'a') + 26),
            b'0'..=b'9' => Some(u32::from(c - b'0') + 52),
            b'+' => Some(62),
            b'/' => Some(63),
            _ => None,
        }
    };
    let bytes: Vec<u8> = text.bytes().filter(|b| !b.is_ascii_whitespace()).collect();
    if !bytes.len().is_multiple_of(4) {
        return None;
    }
    let mut out = Vec::with_capacity(bytes.len() / 4 * 3);
    for chunk in bytes.chunks(4) {
        let pad = chunk.iter().rev().take_while(|&&b| b == b'=').count();
        let mut n = 0u32;
        for &b in &chunk[..4 - pad] {
            n = (n << 6) | value(b)?;
        }
        n <<= 6 * pad as u32;
        let decoded = [(n >> 16) as u8, (n >> 8) as u8, n as u8];
        out.extend_from_slice(&decoded[..3 - pad]);
    }
    Some(out)
}

fn invalid(message: impl Into<String>) -> EngineError {
    EngineError::Rpc {
        code: EngineError::INVALID_PARAMS,
        message: message.into(),
    }
}

fn read_json(path: &Path) -> Result<Value, EngineError> {
    let text = std::fs::read_to_string(path)?;
    serde_json::from_str(&text).map_err(|e| invalid(format!("{}: not valid JSON: {e}", path.display())))
}

fn parse_json(text: &str, what: &str) -> Result<Value, EngineError> {
    serde_json::from_str(text).map_err(|e| invalid(format!("{what}: not valid JSON: {e}")))
}

/// A dataset list: a JSON list, or an object with a `datasets` list (the output of `import`).
fn read_datasets(path: &Path) -> Result<Value, EngineError> {
    match read_json(path)? {
        Value::Array(list) => Ok(Value::Array(list)),
        Value::Object(mut map) => map
            .remove("datasets")
            .filter(Value::is_array)
            .ok_or_else(|| invalid(format!("{}: no `datasets` list", path.display()))),
        _ => Err(invalid(format!("{}: expected a list of datasets", path.display()))),
    }
}

/// A model spec, or an object with a `model` spec (the output of `model` or `fit`).
fn read_model(path: &Path) -> Result<Value, EngineError> {
    let value = read_json(path)?;
    Ok(match value.get("model") {
        Some(model) if model.is_object() => model.clone(),
        _ => value,
    })
}

/// `NAME=FILE` model arguments as `[{name, model}]` (the file holds a spec or a fit/model output).
fn named_models(args: &[String]) -> Result<Value, EngineError> {
    let mut list = Vec::new();
    for arg in args {
        let (name, file) = arg
            .split_once('=')
            .ok_or_else(|| invalid(format!("--model expects NAME=FILE, got `{arg}`")))?;
        list.push(json!({"name": name, "model": read_model(Path::new(file))?}));
    }
    Ok(Value::Array(list))
}

fn path_string(path: &Path) -> Result<String, EngineError> {
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(|| invalid(format!("{}: path is not valid UTF-8", path.display())))
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    let cli = Cli::parse();
    match run(cli).await {
        Ok(text) => {
            println!("{text}");
            ExitCode::SUCCESS
        }
        Err(err) => {
            eprintln!("error: {err}");
            ExitCode::FAILURE
        }
    }
}

async fn run(cli: Cli) -> Result<String, EngineError> {
    let result = match cli.command {
        // Project files need no worker.
        Command::Project { action } => project_action(action),
        command => {
            let python = match cli.python {
                Some(path) => path,
                None => resolve_worker_python(None)?,
            };
            let mut worker = WorkerCommand::python_worker(python);
            if let Some(dir) = cli.components_dir {
                worker = worker.with_env("PB_COMPONENTS_DIR", dir);
            }
            if let Some(dir) = cli.envs_dir {
                worker = worker.with_env("PB_ENVS_DIR", dir);
            }
            let engine = Engine::new(EngineConfig::new(worker));
            let result = execute(&engine, command).await;
            engine.shutdown().await;
            result
        }
    };
    let text = serde_json::to_string_pretty(&result?).map_err(|e| EngineError::Protocol(e.to_string()))?;
    match cli.output_file {
        Some(path) => {
            std::fs::write(&path, text + "\n")?;
            Ok(format!("wrote {}", path.display()))
        }
        None => Ok(text),
    }
}

async fn execute(engine: &Engine, command: Command) -> Result<Value, EngineError> {
    let (method, params) = match command {
        Command::Property {
            fluid,
            pair,
            values,
            output,
        } => {
            let [v1, v2] = values[..] else {
                return Err(EngineError::Rpc {
                    code: EngineError::INVALID_PARAMS,
                    message: "--values needs exactly two numbers".into(),
                });
            };
            let result = engine
                .property(&PropertyRequest {
                    fluid,
                    pair,
                    values: [v1, v2],
                    output,
                })
                .await?;
            return serde_json::to_value(result).map_err(|e| EngineError::Protocol(e.to_string()));
        }
        Command::Fluids => (Method::Fluids, Value::Null),
        Command::Import {
            file,
            mapping,
            fluid,
            name,
        } => {
            let mapping = mapping.as_deref().map(read_json).transpose()?;
            let params = json!({"path": path_string(&file)?, "mapping": mapping, "fluid": fluid, "name": name});
            (Method::DatasetImport, params)
        }
        Command::Check { data } => (Method::DatasetCheck, json!({"datasets": read_datasets(&data)?})),
        Command::Model {
            kind,
            fluid,
            reference_fluid,
        } => (
            Method::ModelDefault,
            json!({"kind": kind, "fluid": fluid, "reference_fluid": reference_fluid}),
        ),
        Command::Fit { model, data, options } => {
            let options = options.as_deref().map(|o| parse_json(o, "--options")).transpose()?;
            let params = json!({"model": read_model(&model)?, "datasets": read_datasets(&data)?, "options": options});
            (Method::ModelFit, params)
        }
        Command::Validate {
            model,
            data,
            methods,
            options,
            k,
            n_bootstrap,
            seed,
            workers,
        } => {
            let options = options.as_deref().map(|o| parse_json(o, "--options")).transpose()?;
            let params = json!({
                "model": read_model(&model)?, "datasets": read_datasets(&data)?, "methods": methods,
                "options": options, "k": k, "n_bootstrap": n_bootstrap, "seed": seed, "workers": workers,
            });
            (Method::StudyValidate, params)
        }
        Command::Consistency {
            data,
            models,
            no_references,
            t_tol,
        } => {
            let params = json!({
                "datasets": read_datasets(&data)?, "models": named_models(&models)?,
                "include_references": !no_references, "t_tol": t_tol,
            });
            (Method::ConsistencyAnalyze, params)
        }
        Command::Compare {
            data,
            models,
            no_references,
        } => {
            let params = json!({
                "datasets": read_datasets(&data)?, "models": named_models(&models)?,
                "include_references": !no_references,
            });
            (Method::ModelCompare, params)
        }
        Command::Project { action } => return project_action(action),
        Command::Report { spec, out } => {
            let format = out
                .extension()
                .and_then(|e| e.to_str())
                .map(str::to_ascii_lowercase)
                .ok_or_else(|| invalid("--out needs an extension (pdf, docx, md, zip)"))?;
            let result = engine
                .invoke(
                    Method::ReportRender,
                    json!({ "spec": read_json(&spec)?, "format": format }),
                )
                .await?;
            return write_content(&result, &out);
        }
        Command::ExportCoolprop { model, out, name, data } => {
            let datasets = match data {
                Some(path) => read_datasets(&path)?,
                None => Value::Null,
            };
            let params = json!({ "model": read_model(&model)?, "name": name, "datasets": datasets });
            let result = engine.invoke(Method::ModelExportCoolProp, params).await?;
            let verification = result.get("verification").cloned().unwrap_or(Value::Null);
            if verification.get("identical").and_then(Value::as_bool) != Some(true) {
                return Err(invalid(format!(
                    "CoolProp does not reproduce the model: {verification}"
                )));
            }
            let text = result.get("json").and_then(Value::as_str).unwrap_or_default();
            std::fs::write(&out, text)?;
            return Ok(json!({ "written": path_string(&out)?, "verification": verification }));
        }
        Command::Figure { spec, out, dpi } => {
            let format = out
                .extension()
                .and_then(|e| e.to_str())
                .map(str::to_ascii_lowercase)
                .ok_or_else(|| invalid("--out needs an extension (svg, pdf, eps, png, tiff)"))?;
            let params = json!({ "spec": read_json(&spec)?, "format": format, "dpi": dpi });
            let result = engine.invoke(Method::FigureRender, params).await?;
            let content = result
                .get("content_base64")
                .and_then(Value::as_str)
                .ok_or_else(|| EngineError::Protocol("figure.render returned no content".into()))?;
            let bytes =
                base64_decode(content).ok_or_else(|| EngineError::Protocol("figure content is not base64".into()))?;
            std::fs::write(&out, &bytes)?;
            return Ok(json!({ "written": path_string(&out)?, "bytes": bytes.len(), "format": format }));
        }
        Command::Env { action } => match action {
            EnvAction::Status { project } => (Method::EnvStatus, json!({ "project": project })),
            EnvAction::Create { project } => (Method::EnvCreate, json!({ "project": project })),
            EnvAction::Install { project, packages } => {
                (Method::EnvInstall, json!({ "project": project, "packages": packages }))
            }
            EnvAction::Sync { project, lock } => {
                let lock = std::fs::read_to_string(&lock)?;
                (Method::EnvSync, json!({ "project": project, "lock": lock }))
            }
            EnvAction::Run {
                project,
                script,
                timeout,
                memory_mb,
            } => {
                let code = std::fs::read_to_string(&script)?;
                let params = json!({ "project": project, "code": code, "timeout": timeout, "memory_mb": memory_mb });
                (Method::EnvRun, params)
            }
        },
        Command::Components { action } => match action {
            ComponentsAction::List { registry } => (Method::ComponentsList, json!({ "registry": registry })),
            ComponentsAction::Install { id, registry } => {
                (Method::ComponentsInstall, json!({ "id": id, "registry": registry }))
            }
            ComponentsAction::InstallFile { archive } => {
                let bytes = std::fs::read(&archive)?;
                (
                    Method::ComponentsInstallFile,
                    json!({ "content_base64": base64(&bytes) }),
                )
            }
            ComponentsAction::Remove { id } => (Method::ComponentsRemove, json!({ "id": id })),
        },
        Command::Call { method, params } => {
            let method = Method::from_name(&method).ok_or_else(|| {
                let known: Vec<&str> = Method::ALL.iter().map(|m| m.name()).collect();
                invalid(format!("unknown method `{method}` (known: {})", known.join(", ")))
            })?;
            (method, parse_json(&params, "params")?)
        }
    };
    engine.invoke(method, params).await
}

#[cfg(test)]
mod tests {
    use super::base64;

    #[test]
    fn base64_matches_rfc_4648_vectors() {
        let cases = [
            ("", ""),
            ("f", "Zg=="),
            ("fo", "Zm8="),
            ("foo", "Zm9v"),
            ("foobar", "Zm9vYmFy"),
        ];
        for (plain, encoded) in cases {
            assert_eq!(base64(plain.as_bytes()), encoded);
        }
        assert_eq!(base64(&[0xff, 0xfe, 0x00]), "//4A");
    }

    #[test]
    fn base64_decode_inverts_encode() {
        for plain in [&b""[..], b"f", b"fo", b"foo", b"foobar", &[0xff, 0xfe, 0x00, 0x10]] {
            assert_eq!(super::base64_decode(&base64(plain)).as_deref(), Some(plain));
        }
        assert_eq!(super::base64_decode("abc"), None);
        assert_eq!(super::base64_decode("ab!="), None);
    }
}
