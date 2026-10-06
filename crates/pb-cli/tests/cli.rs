#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::process::Command;

fn propbench(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_propbench"))
        .args(args)
        .output()
        .unwrap()
}

#[test]
fn property_prints_acceptance_value_as_json() {
    let out = propbench(&[
        "property",
        "--fluid",
        "R134a",
        "--pair",
        "PT_INPUTS",
        "--values",
        "1e6,300",
        "--output",
        "Dmass",
    ]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!((json["value"].as_f64().unwrap() - 1201.53).abs() < 0.005, "{json}");
}

#[test]
fn backend_error_exits_non_zero_with_message() {
    let out = propbench(&[
        "property",
        "--fluid",
        "NotAFluid",
        "--pair",
        "PT_INPUTS",
        "--values",
        "1e6,300",
        "--output",
        "Dmass",
    ]);
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("NotAFluid"));
}

#[test]
fn values_need_exactly_two_numbers() {
    let out = propbench(&[
        "property",
        "--fluid",
        "R134a",
        "--pair",
        "PT_INPUTS",
        "--values",
        "1e6",
        "--output",
        "Dmass",
    ]);
    assert!(!out.status.success());
}

fn json_of(out: &std::process::Output) -> serde_json::Value {
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    serde_json::from_slice(&out.stdout).unwrap()
}

/// The full workflow on the command line: properties → CSV → import → model → fit → validate.
#[test]
fn import_fit_validate_workflow() {
    let dir = std::path::Path::new(env!("CARGO_TARGET_TMPDIR")).join("cli_workflow");
    std::fs::create_dir_all(&dir).unwrap();
    let path = |name: &str| dir.join(name).to_str().unwrap().to_owned();

    // reference viscosities of R236fa from CoolProp, written as an experimental-style CSV in µPa·s and MPa
    let states: Vec<(f64, f64)> = [260.0, 300.0, 340.0]
        .iter()
        .flat_map(|&t| [1.0e5, 2.0e6, 1.0e7].map(|p| (t, p)))
        .collect();
    let params = serde_json::json!({
        "fluid": "R236FA", "pair": "PT_INPUTS", "outputs": ["V"],
        "values1": states.iter().map(|s| s.1).collect::<Vec<_>>(),
        "values2": states.iter().map(|s| s.0).collect::<Vec<_>>(),
    });
    let eta = json_of(&propbench(&["call", "properties", &params.to_string()]));
    let mut csv = String::from("T,p,eta\n");
    for (i, (t, p)) in states.iter().enumerate() {
        let v = eta["outputs"]["V"][i].as_f64().unwrap();
        csv.push_str(&format!("{t},{},{}\n", p / 1e6, v * 1e6));
    }
    std::fs::write(path("eta.csv"), csv).unwrap();
    let mapping = serde_json::json!({
        "kind": "propbench.import-mapping", "version": 1, "quantity": "viscosity",
        "columns": [
            {"column": "T", "role": "temperature", "unit": "K"},
            {"column": "p", "role": "pressure", "unit": "MPa"},
            {"column": "eta", "role": "value", "unit": "uPa*s"}
        ]
    });
    std::fs::write(path("mapping.json"), mapping.to_string()).unwrap();

    let imported = propbench(&[
        "import",
        &path("eta.csv"),
        "--mapping",
        &path("mapping.json"),
        "--fluid",
        "R236FA",
        "-o",
        &path("data.json"),
    ]);
    assert!(
        imported.status.success(),
        "{}",
        String::from_utf8_lossy(&imported.stderr)
    );
    let model = propbench(&[
        "model",
        "--kind",
        "ecs_viscosity",
        "--fluid",
        "R236FA",
        "-o",
        &path("model.json"),
    ]);
    assert!(model.status.success(), "{}", String::from_utf8_lossy(&model.stderr));

    let fit = json_of(&propbench(&[
        "fit",
        "--model",
        &path("model.json"),
        "--data",
        &path("data.json"),
        "--options",
        r#"{"fixed": {"psi_2": true}}"#,
    ]));
    assert!(fit["summary"]["deviations"]["aard"].as_f64().unwrap() < 0.5, "{fit}");

    let study = json_of(&propbench(&[
        "validate",
        "--model",
        &path("model.json"),
        "--data",
        &path("data.json"),
        "--methods",
        "kfold,loto",
        "--k",
        "3",
        "--options",
        r#"{"fixed": {"psi_2": true}}"#,
    ]));
    assert_eq!(study["cross_validation"]["kfold"]["pooled"]["n"], 9);
    assert!(study["physics"].as_array().unwrap().len() >= 3);
}

#[test]
fn unknown_method_is_rejected_before_reaching_the_worker() {
    let out = propbench(&["call", "os.system", "{}"]);
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("unknown method"));
}
