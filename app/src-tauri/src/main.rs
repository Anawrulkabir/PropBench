//! PropBench desktop shell. The UI never computes: every action is a Tauri command that calls `pb-engine`, which
//! runs the science in the Python worker (CLAUDE.md rule 2).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use std::process::ExitCode;

use tauri::{Manager, RunEvent, Runtime};

/// Everything the app registers, shared by `main` and the IPC tests.
fn builder<R: Runtime>(builder: tauri::Builder<R>) -> tauri::Builder<R> {
    builder
        .plugin(tauri_plugin_dialog::init())
        .manage(commands::AppEngine::default())
        .manage(commands::Terminals::default())
        .manage(commands::RemoteEngine::default())
        .invoke_handler(tauri::generate_handler![
            commands::property,
            commands::worker,
            commands::cancel,
            commands::project_save,
            commands::project_open,
            commands::project_autosave,
            commands::project_recover,
            commands::project_discard_autosave,
            commands::terminal_open,
            commands::terminal_write,
            commands::terminal_resize,
            commands::terminal_close,
            commands::remote_connect,
            commands::remote_disconnect,
            commands::secret_set,
            commands::secret_has,
            commands::secret_delete,
            commands::assistant_ask,
            commands::github_signin_start,
            commands::github_signin_poll,
            commands::github_push,
            commands::history_commit,
            commands::history_list,
            commands::plugin_list,
            commands::plugin_install,
            commands::plugin_install_component,
            commands::plugin_approve,
            commands::plugin_revoke,
            commands::plugin_remove,
            commands::plugin_trust,
            commands::plugin_predict,
            commands::plugin_check,
            commands::plugin_python,
            commands::plugin_run
        ])
}

fn main() -> ExitCode {
    let app = match builder(tauri::Builder::default()).build(tauri::generate_context!()) {
        Ok(app) => app,
        Err(err) => {
            eprintln!("PropBench failed to start: {err}");
            return ExitCode::FAILURE;
        }
    };
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            let engine = handle.state::<commands::AppEngine>();
            tauri::async_runtime::block_on(engine.shutdown());
        }
    });
    ExitCode::SUCCESS
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use tauri::Manager;
    use tauri::ipc::{CallbackFn, InvokeBody};
    use tauri::test::{INVOKE_KEY, get_ipc_response, mock_builder, mock_context, noop_assets};
    use tauri::webview::InvokeRequest;

    /// Sends a command through Tauri's IPC exactly as `app/src/lib/api.ts` does, and runs it in the real worker.
    fn invoke(args: serde_json::Value) -> Result<serde_json::Value, serde_json::Value> {
        invoke_cmd("property", args)
    }

    fn invoke_cmd(cmd: &str, args: serde_json::Value) -> Result<serde_json::Value, serde_json::Value> {
        let app = super::builder(mock_builder())
            .build(mock_context(noop_assets()))
            .unwrap();
        let webview = tauri::WebviewWindowBuilder::new(&app, "main", Default::default())
            .build()
            .unwrap();
        let response = get_ipc_response(
            &webview,
            InvokeRequest {
                cmd: cmd.into(),
                callback: CallbackFn(0),
                error: CallbackFn(1),
                url: if cfg!(windows) {
                    "http://tauri.localhost"
                } else {
                    "tauri://localhost"
                }
                .parse()
                .unwrap(),
                body: InvokeBody::Json(args),
                headers: Default::default(),
                invoke_key: INVOKE_KEY.to_string(),
            },
        );
        let result = response.map(|body| body.deserialize::<serde_json::Value>().unwrap());
        tauri::async_runtime::block_on(app.state::<super::commands::AppEngine>().shutdown());
        result
    }

    #[test]
    fn ui_request_reaches_the_worker_over_ipc() {
        let request = json!({ "fluid": "R134a", "pair": "PT_INPUTS", "values": [1.0e6, 300.0], "output": "Dmass" });
        let result = invoke(json!({ "request": request })).unwrap();
        assert!((result["value"].as_f64().unwrap() - 1201.53).abs() < 0.005, "{result}");
        assert_eq!(result["backend"], "CoolProp::HEOS");
    }

    #[test]
    fn backend_errors_reach_the_ui_with_a_kind() {
        let request = json!({ "fluid": "NotAFluid", "pair": "PT_INPUTS", "values": [1.0e6, 300.0], "output": "Dmass" });
        let err = invoke(json!({ "request": request })).unwrap_err();
        assert_eq!(err["kind"], "property");
        assert!(err["message"].as_str().unwrap().contains("NotAFluid"));
    }

    #[test]
    fn credential_methods_cannot_be_called_from_the_ui() {
        let err = invoke_cmd(
            "worker",
            json!({ "method": "assistant.ask", "params": { "provider": "openai", "model": "m", "messages": [] } }),
        )
        .unwrap_err();
        assert_eq!(err["kind"], "invalid_input");
        let err = invoke_cmd("secret_set", json!({ "name": "ssh.key", "value": "x" })).unwrap_err();
        assert_eq!(err["kind"], "invalid_input", "only ai.* and github.* credentials");
    }

    #[test]
    fn worker_methods_reach_the_worker_over_ipc() {
        let kinds = invoke_cmd("worker", json!({ "method": "model.kinds" })).unwrap();
        assert!(kinds["kinds"].as_array().unwrap().len() >= 3, "{kinds}");
        let err = invoke_cmd("worker", json!({ "method": "os.system", "params": {} })).unwrap_err();
        assert_eq!(err["kind"], "invalid_input");
        let err = invoke_cmd(
            "worker",
            json!({ "method": "model.default", "params": { "kind": "nope", "fluid": "R134a" } }),
        )
        .unwrap_err();
        assert_eq!(err["kind"], "propbench");
    }
}
