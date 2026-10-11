//! PropBench storage (README §4): project files and the job result cache.
//!
//! A project is one `.pbp` file, an SQLite database: datasets, named JSON documents (settings, candidate models and
//! their results, masks, the locked selection rule, ...), snapshots and an audit log. Saves are atomic: the whole
//! file is written next to the target and renamed over it, so a crash never leaves a half-written project.
//! Every schema change bumps [`SCHEMA_VERSION`] and adds a migration (CLAUDE.md engine and storage rules).
//!
//! The job cache keeps worker results by job key (method, parameters, worker version) in the app data folder, so
//! a study interrupted by a crash resumes without recomputing finished jobs.

mod atomic;
mod cache;
mod error;
mod project;

pub use atomic::{atomic_write_with, temp_path};
pub use cache::{CacheEntry, ResultCache};
pub use error::StoreError;
pub use project::{
    APPLICATION_ID, AuditEntry, DatasetRecord, FORMAT, Meta, Project, SCHEMA_VERSION, Snapshot, now_seconds,
};
