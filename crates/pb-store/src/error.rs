use std::path::PathBuf;

use thiserror::Error;

/// Why a project file or the result cache could not be read or written.
#[derive(Debug, Error)]
pub enum StoreError {
    #[error("{path}: not a PropBench project file")]
    NotAProject { path: PathBuf },
    #[error("{path}: made by a newer PropBench (project format {found}, this version reads up to {supported})")]
    TooNew { path: PathBuf, found: i64, supported: i64 },
    #[error("{path}: {message}")]
    Corrupt { path: PathBuf, message: String },
    #[error("invalid project content: {0}")]
    Invalid(String),
    #[error("database error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("file error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}
