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

/// Consistency and comparison on the command line, with a planted 3 % offset between two datasets.
#[test]
fn consistency_and_compare() {
    let dir = std::path::Path::new(env!("CARGO_TARGET_TMPDIR")).join("cli_consistency");
    std::fs::create_dir_all(&dir).unwrap();
    let path = |name: &str| dir.join(name).to_str().unwrap().to_owned();
    let states: Vec<(f64, f64)> = [300.0, 320.0]
        .iter()
        .flat_map(|&t| [2.0e6, 5.0e6, 1.0e7].map(|p| (t, p)))
        .collect();
    let params = serde_json::json!({
        "fluid": "R236FA", "pair": "PT_INPUTS", "outputs": ["V"],
        "values1": states.iter().map(|s| s.1).collect::<Vec<_>>(),
        "values2": states.iter().map(|s| s.0).collect::<Vec<_>>(),
    });
    let eta = json_of(&propbench(&["call", "properties", &params.to_string()]));
    let dataset = |name: &str, factor: f64| {
        serde_json::json!({
            "schema_version": 1, "name": name, "fluid": "R236FA", "quantity": "viscosity",
            "temperature": states.iter().map(|s| s.0).collect::<Vec<_>>(),
            "pressure": states.iter().map(|s| s.1).collect::<Vec<_>>(),
            "values": (0..states.len()).map(|i| eta["outputs"]["V"][i].as_f64().unwrap() * factor).collect::<Vec<_>>(),
            "expanded_uncertainty": (0..states.len()).map(|i| eta["outputs"]["V"][i].as_f64().unwrap() * 0.02).collect::<Vec<_>>(),
        })
    };
    let data = serde_json::json!([dataset("a", 1.0), dataset("b", 1.03)]);
    std::fs::write(path("data.json"), data.to_string()).unwrap();

    let report = json_of(&propbench(&["consistency", "--data", &path("data.json")]));
    let offsets = report["offsets"].as_array().unwrap();
    let b_vs_a = offsets
        .iter()
        .find(|o| o["dataset"] == "b" && o["reference"] == "a")
        .unwrap();
    // a straight trend in p on each isotherm leaves a small curvature residual even at identical states
    assert!((b_vs_a["offset"].as_f64().unwrap() - 3.0).abs() < 0.1, "{b_vs_a}");
    assert_eq!(report["models"][0], "CoolProp viscosity correlation");

    let rows = json_of(&propbench(&["compare", "--data", &path("data.json")]));
    let b = rows["rows"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["dataset"] == "b")
        .unwrap();
    assert!((b["deviations"]["bias"].as_f64().unwrap() - 3.0).abs() < 1e-6, "{b}");

    let bad = propbench(&["compare", "--data", &path("data.json"), "--model", "nofile"]);
    assert!(!bad.status.success());
    assert!(String::from_utf8_lossy(&bad.stderr).contains("NAME=FILE"));
}

#[test]
fn project_files_round_trip_through_the_cli() {
    let dir = std::env::temp_dir().join(format!("pb-cli-project-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("cf3i.pbp");
    let file = file.to_str().unwrap();
    let data = dir.join("data.json");
    std::fs::write(
        &data,
        r#"{"datasets": [{"name": "d1", "fluid": "R13I1", "quantity": "viscosity", "values": [1e-4, 2e-4]}]}"#,
    )
    .unwrap();

    let ok = |args: &[&str]| {
        let out = propbench(args);
        assert!(
            out.status.success(),
            "{:?}: {}",
            args,
            String::from_utf8_lossy(&out.stderr)
        );
        serde_json::from_slice::<serde_json::Value>(&out.stdout).unwrap()
    };
    ok(&["project", "new", file, "--name", "CF3I"]);
    assert_eq!(
        ok(&["project", "add-datasets", file, "--data", data.to_str().unwrap()])["added"][0],
        "d1"
    );
    assert_eq!(ok(&["project", "snapshot", file, "--label", "imported"])["snapshot"], 1);
    let info = ok(&["project", "info", file]);
    assert_eq!(info["meta"]["name"], "CF3I");
    assert_eq!(info["datasets"][0]["points"], 2);
    assert_eq!(info["snapshots"][0]["label"], "imported");

    let json = dir.join("export.json");
    let copy = dir.join("copy.pbp");
    assert!(
        propbench(&["project", "export", file, "-o", json.to_str().unwrap()])
            .status
            .success()
    );
    ok(&["project", "import", json.to_str().unwrap(), copy.to_str().unwrap()]);
    assert_eq!(
        ok(&["project", "info", copy.to_str().unwrap()])["datasets"],
        info["datasets"]
    );

    std::fs::write(dir.join("bad.pbp"), b"not a project").unwrap();
    let out = propbench(&["project", "info", dir.join("bad.pbp").to_str().unwrap()]);
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("not a PropBench project"));
}

#[test]
fn project_files_are_shared_with_the_python_package() {
    let python = pb_engine::resolve_worker_python(None).expect("worker Python: run `uv sync --project worker`");
    let dir = std::env::temp_dir().join(format!("pb-cli-pyproject-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let from_py = dir.join("from_python.pbp");
    let from_rust = dir.join("from_rust.pbp");
    let script = format!(
        "from propbench import project\n\
         p = project.new('made in Python')\n\
         p['datasets'].append({{'name': 'd', 'data': {{'name': 'd', 'fluid': 'R13I1', 'quantity': 'viscosity', 'values': [1.0]}}}})\n\
         project.save({:?}, p)\n\
         q = project.load({:?})\n\
         assert q['meta']['name'] == 'made in Rust', q\n\
         assert q['snapshots'][0]['label'] == 'snap'\n",
        from_py.to_str().unwrap(),
        from_rust.to_str().unwrap()
    );
    let out = propbench(&["project", "new", from_rust.to_str().unwrap(), "--name", "made in Rust"]);
    assert!(out.status.success());
    assert!(
        propbench(&["project", "snapshot", from_rust.to_str().unwrap(), "--label", "snap"])
            .status
            .success()
    );
    let py = Command::new(python).args(["-I", "-c", &script]).output().unwrap();
    assert!(py.status.success(), "{}", String::from_utf8_lossy(&py.stderr));
    let info = propbench(&["project", "info", from_py.to_str().unwrap()]);
    let info: serde_json::Value = serde_json::from_slice(&info.stdout).unwrap();
    assert_eq!(info["meta"]["name"], "made in Python");
    assert_eq!(info["datasets"][0]["fluid"], "R13I1");
}

#[test]
fn components_install_offline_list_and_remove() {
    let python = pb_engine::resolve_worker_python(None).expect("worker Python: run `uv sync --project worker`");
    let dir = std::env::temp_dir().join(format!("pb-cli-components-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("src")).unwrap();
    std::fs::write(
        dir.join("src").join("component.json"),
        r#"{"id": "demo-data", "name": "Demo data", "version": "1.0", "kind": "data"}"#,
    )
    .unwrap();
    std::fs::write(dir.join("src").join("datasets.json"), r#"{"datasets": []}"#).unwrap();
    let archive = dir.join("demo-data-1.0.zip");
    let script = format!(
        "from propbench import components\ncomponents.build_archive({:?}, {:?})\n",
        dir.join("src").to_str().unwrap(),
        archive.to_str().unwrap()
    );
    assert!(
        Command::new(python)
            .args(["-I", "-c", &script])
            .status()
            .unwrap()
            .success()
    );
    let root = dir.join("appdata");
    let root = root.to_str().unwrap();
    let run = |args: &[&str]| {
        let mut all = vec!["--components-dir", root];
        all.extend_from_slice(args);
        let out = propbench(&all);
        assert!(
            out.status.success(),
            "{args:?}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        serde_json::from_slice::<serde_json::Value>(&out.stdout).unwrap()
    };
    let installed = run(&["components", "install-file", archive.to_str().unwrap()]);
    assert_eq!(installed["installed"][0]["id"], "demo-data");
    let missing_registry = dir.join("none.json");
    let listing = run(&["components", "list", "--registry", missing_registry.to_str().unwrap()]);
    assert_eq!(listing["installed"][0]["version"], "1.0");
    assert!(
        listing["registry_error"].is_string(),
        "offline: the registry error is reported, not fatal"
    );
    run(&["components", "remove", "demo-data"]);
    let listing = run(&["components", "list", "--registry", missing_registry.to_str().unwrap()]);
    assert_eq!(listing["installed"], serde_json::json!([]));
}

#[test]
fn env_run_executes_in_the_project_environment() {
    let dir = std::env::temp_dir().join(format!("pb-cli-envs-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let script = dir.join("hello.py");
    std::fs::write(&script, "import sys, propbench\nprint('prefix', sys.prefix)\n").unwrap();
    let envs = dir.join("envs");
    let out = propbench(&[
        "--envs-dir",
        envs.to_str().unwrap(),
        "env",
        "run",
        "CF3I demo",
        script.to_str().unwrap(),
        "--timeout",
        "120",
    ]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(json["exit_code"], 0, "{json}");
    let stdout = json["stdout"].as_str().unwrap();
    assert!(
        stdout.contains("cf3i-demo"),
        "the script ran inside the project environment: {stdout}"
    );
}

#[test]
fn figure_renders_a_pdf() {
    let dir = std::env::temp_dir().join(format!("pb-cli-figure-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let spec = dir.join("spec.json");
    std::fs::write(
        &spec,
        r#"{"preset": "acs1", "x": {"label": "T / K"}, "y": {"label": "y"},
            "layers": [{"type": "points", "name": "d", "x": [300, 310], "y": [1, 2]}]}"#,
    )
    .unwrap();
    let out = dir.join("fig.pdf");
    let res = propbench(&["figure", spec.to_str().unwrap(), "--out", out.to_str().unwrap()]);
    assert!(res.status.success(), "{}", String::from_utf8_lossy(&res.stderr));
    assert!(std::fs::read(&out).unwrap().starts_with(b"%PDF"));
}

#[test]
fn export_coolprop_writes_a_verified_fluid_file() {
    let dir = std::env::temp_dir().join(format!("pb-cli-export-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let model = dir.join("model.json");
    let out = propbench(&[
        "model",
        "--kind",
        "ecs_viscosity",
        "--fluid",
        "R236FA",
        "-o",
        model.to_str().unwrap(),
    ]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let fluid = dir.join("R236FA-cli.json");
    let res = propbench(&[
        "export-coolprop",
        model.to_str().unwrap(),
        "--out",
        fluid.to_str().unwrap(),
        "--name",
        "R236FA-cli",
    ]);
    assert!(res.status.success(), "{}", String::from_utf8_lossy(&res.stderr));
    let json: serde_json::Value = serde_json::from_slice(&res.stdout).unwrap();
    assert_eq!(json["verification"]["identical"], true, "{json}");
    assert!(std::fs::read_to_string(&fluid).unwrap().contains("\"ECS\""));
}

#[test]
fn history_commit_and_log() {
    let dir = std::env::temp_dir().join(format!("pb-cli-history-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("p.pbp");
    let f = file.to_str().unwrap();
    assert!(propbench(&["project", "new", f, "--name", "History"]).status.success());
    let out = propbench(&["history", "commit", f, "-m", "first"]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let again = propbench(&["history", "commit", f, "-m", "unchanged"]);
    assert_eq!(
        String::from_utf8_lossy(&again.stdout).trim(),
        "null",
        "no commit when nothing changed"
    );
    let log: serde_json::Value = serde_json::from_slice(&propbench(&["history", "log", f]).stdout).unwrap();
    assert_eq!(log.as_array().unwrap().len(), 1);
    assert_eq!(log[0]["message"], "first");
    assert!(dir.join("p.history").join("project.json").is_file());
}
