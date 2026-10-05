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
    /// Cross-validate a model (loso, loto, kfold, bootstrap) and run the physics checks.
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
    /// Any worker operation by name with JSON params, e.g. `call selection.lock '{"rule": {...}}'`.
    Call {
        method: String,
        #[arg(default_value = "{}")]
        params: String,
    },
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
    let python = match cli.python {
        Some(path) => path,
        None => resolve_worker_python(None)?,
    };
    let engine = Engine::new(EngineConfig::new(WorkerCommand::python_worker(python)));
    let result = execute(&engine, cli.command).await;
    engine.shutdown().await;
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
