//! Project files: round trip, atomic saves, refusal of foreign and newer files, snapshots; result cache.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::path::PathBuf;

use pb_store::{APPLICATION_ID, DatasetRecord, Project, ResultCache, SCHEMA_VERSION, StoreError, temp_path};
use rusqlite::Connection;
use serde_json::json;

fn dir(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("pb-store-test-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn sample() -> Project {
    let mut p = Project::new("CF3I viscosity");
    p.meta.app_version = "0.1.0".into();
    p.datasets.push(DatasetRecord {
        name: "tuhin2024_liquid".into(),
        data: json!({"name": "tuhin2024_liquid", "fluid": "R13I1", "quantity": "viscosity",
                     "temperature": [332.96, 353.31], "values": [2.0371e-4, 1.6702e-4]}),
    });
    p.datasets.push(DatasetRecord {
        name: "duan1999".into(),
        data: json!({"name": "duan1999", "fluid": "R13I1", "quantity": "viscosity", "values": [4.513e-4]}),
    });
    p.documents
        .insert("settings".into(), json!({"seed": 2026, "methods": ["lostate"]}));
    p.documents.insert("masks".into(), json!({"duan1999": [3, 7]}));
    p.log("import", "2 datasets");
    p
}

#[test]
fn project_round_trips_exactly() {
    let d = dir("roundtrip");
    let path = d.join("cf3i.pbp");
    let mut p = sample();
    p.snapshot("before fitting");
    p.save(&path).unwrap();
    let back = Project::load(&path).unwrap();
    assert_eq!(back, p);
    assert_eq!(back.meta.schema_version, SCHEMA_VERSION);
    assert_eq!(back.datasets[0].name, "tuhin2024_liquid", "dataset order is kept");
    assert!(!temp_path(&path).exists(), "no temporary file is left behind");
}

#[test]
fn file_is_an_sqlite_database_with_the_project_header() {
    let d = dir("header");
    let path = d.join("p.pbp");
    sample().save(&path).unwrap();
    let conn = Connection::open(&path).unwrap();
    let app_id: i64 = conn.query_row("PRAGMA application_id", [], |r| r.get(0)).unwrap();
    let version: i64 = conn.query_row("PRAGMA user_version", [], |r| r.get(0)).unwrap();
    assert_eq!((app_id, version), (APPLICATION_ID, SCHEMA_VERSION));
    let fluid: String = conn
        .query_row("SELECT fluid FROM datasets WHERE name = 'duan1999'", [], |r| r.get(0))
        .unwrap();
    assert_eq!(fluid, "R13I1", "fluid and quantity are queryable columns");
}

#[test]
fn a_failed_save_leaves_the_old_file_untouched() {
    let d = dir("atomic");
    let path = d.join("p.pbp");
    let original = sample();
    original.save(&path).unwrap();
    let mut bad = sample();
    bad.datasets.push(bad.datasets[0].clone()); // duplicate name: refused before anything is written
    assert!(matches!(bad.save(&path), Err(StoreError::Invalid(_))));
    assert_eq!(Project::load(&path).unwrap(), original);
    // A write that fails half way (here: the target's folder is a file) never replaces the project.
    let blocked = d.join("not-a-dir");
    std::fs::write(&blocked, b"x").unwrap();
    assert!(sample().save(&blocked.join("p.pbp")).is_err());
    assert_eq!(std::fs::read(&blocked).unwrap(), b"x");
}

#[test]
fn saving_over_an_existing_file_replaces_it() {
    let d = dir("replace");
    let path = d.join("p.pbp");
    sample().save(&path).unwrap();
    let mut changed = sample();
    changed.datasets.truncate(1);
    changed.meta.name = "renamed".into();
    changed.save(&path).unwrap();
    let back = Project::load(&path).unwrap();
    assert_eq!(back.datasets.len(), 1);
    assert_eq!(back.meta.name, "renamed");
}

#[test]
fn foreign_and_newer_files_are_refused() {
    let d = dir("refuse");
    let text = d.join("notes.pbp");
    std::fs::write(&text, b"hello, not a database").unwrap();
    assert!(matches!(Project::load(&text), Err(StoreError::NotAProject { .. })));

    let other = d.join("other.sqlite");
    Connection::open(&other)
        .unwrap()
        .execute_batch("CREATE TABLE t (x INTEGER);")
        .unwrap();
    assert!(matches!(Project::load(&other), Err(StoreError::NotAProject { .. })));

    let newer = d.join("newer.pbp");
    sample().save(&newer).unwrap();
    Connection::open(&newer)
        .unwrap()
        .execute_batch(&format!("PRAGMA user_version = {};", SCHEMA_VERSION + 1))
        .unwrap();
    match Project::load(&newer) {
        Err(StoreError::TooNew { found, supported, .. }) => {
            assert_eq!((found, supported), (SCHEMA_VERSION + 1, SCHEMA_VERSION));
        }
        other => panic!("expected TooNew, got {other:?}"),
    }
    assert!(Project::load(&d.join("missing.pbp")).is_err());
}

#[test]
fn snapshots_restore_datasets_and_documents() {
    let mut p = sample();
    let id = p.snapshot("imported");
    p.datasets.clear();
    p.documents.insert("settings".into(), json!({"seed": 1}));
    p.restore(id).unwrap();
    assert_eq!(p.datasets.len(), 2);
    assert_eq!(p.documents["settings"]["seed"], 2026);
    assert_eq!(p.snapshots.len(), 1);
    assert_eq!(p.audit.last().unwrap().action, "restore");
    assert!(p.restore(99).is_err());
}

#[test]
fn cache_survives_reopening_and_prunes_least_recently_used() {
    let d = dir("cache");
    let path = d.join("cache.sqlite");
    {
        let cache = ResultCache::open(&path).unwrap();
        cache.put("k1", "model.fit", &json!({"aard": 0.5})).unwrap();
        cache.put("k2", "study.validate", &json!({"folds": 15})).unwrap();
    }
    let cache = ResultCache::open(&path).unwrap();
    assert_eq!(cache.get("k1").unwrap(), Some(json!({"aard": 0.5})));
    assert_eq!(cache.get("nope").unwrap(), None);
    assert_eq!(cache.len().unwrap(), 2);
    cache.put("k3", "model.fit", &json!(3)).unwrap();
    assert_eq!(cache.prune(2).unwrap(), 1);
    assert_eq!(cache.len().unwrap(), 2);
    cache.clear().unwrap();
    assert!(cache.is_empty().unwrap());
}
