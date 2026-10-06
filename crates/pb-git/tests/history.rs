//! Project history: the mirror is committed, unchanged projects make no commit, history is newest first, and
//! the committed files are readable from the Git objects (a valid repository without a Git installation).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use pb_git::{commit, history, mirror_files};
use pb_store::{DatasetRecord, Project};
use serde_json::json;

fn project() -> Project {
    let mut p = Project::new("CF3I viscosity");
    p.datasets.push(DatasetRecord {
        name: "tuhin 2024/liquid".into(),
        data: json!({"name": "tuhin 2024/liquid", "fluid": "R13I1", "quantity": "viscosity",
                     "temperature": [332.96, 353.31], "pressure": [3.999e6, 4.001e6], "values": [2.0882e-4, 1.6746e-4],
                     "point_ids": [0, 1], "expanded_uncertainty": [4.6e-6, 3.7e-6], "phase": ["liquid", "liquid"]}),
    });
    p.documents.insert("settings".into(), json!({"seed": 2026}));
    p.log("import", "tuhin 2024/liquid");
    p
}

#[test]
fn commits_history_and_readable_objects() {
    let dir = std::env::temp_dir().join(format!("pb-git-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let mut p = project();
    let first = commit(&dir, &p, "Import data", "PropBench user", "user@example.org")
        .unwrap()
        .unwrap();
    assert!(
        commit(&dir, &p, "nothing changed", "u", "u@x").unwrap().is_none(),
        "no empty commits"
    );
    p.documents.insert("settings".into(), json!({"seed": 7}));
    let second = commit(&dir, &p, "Change seed", "PropBench user", "user@example.org")
        .unwrap()
        .unwrap();
    let log = history(&dir, 10).unwrap();
    assert_eq!(
        log.iter().map(|c| c.message.as_str()).collect::<Vec<_>>(),
        ["Change seed", "Import data"]
    );
    assert_eq!(log[0].id, second.id);
    assert_eq!(log[1].id, first.id);
    assert_eq!(log[0].author, "PropBench user");

    // the files are in the commit's tree and in the working folder
    let repo = gix::open(&dir).unwrap();
    let tree = repo.head_commit().unwrap().tree().unwrap();
    let entry = tree
        .lookup_entry_by_path("datasets/tuhin_2024_liquid.csv")
        .unwrap()
        .expect("csv in the tree");
    let csv = String::from_utf8(entry.object().unwrap().data.clone()).unwrap();
    assert!(csv.starts_with("point_id,T_K,p_Pa"));
    assert!(csv.contains("0,332.96,3999000.0,,0.00020882,4.6e-6,liquid"), "{csv}");
    assert!(dir.join("project.json").is_file());
    let names: Vec<String> = mirror_files(&p).unwrap().into_keys().collect();
    assert_eq!(
        names,
        [
            "README.md",
            "audit.log",
            "datasets/tuhin_2024_liquid.csv",
            "datasets/tuhin_2024_liquid.json",
            "project.json"
        ]
    );
}
