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
