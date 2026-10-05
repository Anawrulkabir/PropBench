//! `propbench` command line. Every GUI action is available here (CLAUDE.md rule 2).

use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand};
use pb_engine::{Engine, EngineConfig, EngineError, PropertyRequest, WorkerCommand, resolve_worker_python};

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
    let text = match cli.command {
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
                .await;
            engine.shutdown().await;
            serde_json::to_string_pretty(&result?).map_err(|e| EngineError::Protocol(e.to_string()))?
        }
    };
    Ok(text)
}
