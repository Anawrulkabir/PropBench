use std::path::Path;
use std::sync::{Mutex, MutexGuard, PoisonError};

use rusqlite::{Connection, OptionalExtension, params};
use serde_json::Value;

use crate::{StoreError, now_seconds};

const CACHE_SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS results (
    key TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    created INTEGER NOT NULL,
    used INTEGER NOT NULL,
    result TEXT NOT NULL
);
";

/// One cached worker result.
#[derive(Debug, Clone, PartialEq)]
pub struct CacheEntry {
    pub key: String,
    pub method: String,
    pub result: Value,
}

/// Worker results by job key, in an SQLite file in the app data folder (or in memory for tests). Jobs are
/// deterministic given their key (CLAUDE.md), so a cached result is the result. Every `put` is its own committed
/// transaction: a result is either completely stored or not at all, even if the app is killed.
pub struct ResultCache {
    conn: Mutex<Connection>,
}

impl ResultCache {
    /// Open (or create) the cache file at `path`.
    pub fn open(path: &Path) -> Result<Self, StoreError> {
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)?;
        }
        let conn = Connection::open(path)?;
        conn.execute_batch("PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL;")?;
        conn.execute_batch(CACHE_SCHEMA)?;
        Ok(Self { conn: Mutex::new(conn) })
    }

    /// A cache that lives only as long as the process.
    pub fn in_memory() -> Result<Self, StoreError> {
        let conn = Connection::open_in_memory()?;
        conn.execute_batch(CACHE_SCHEMA)?;
        Ok(Self { conn: Mutex::new(conn) })
    }

    fn conn(&self) -> MutexGuard<'_, Connection> {
        self.conn.lock().unwrap_or_else(PoisonError::into_inner)
    }

    pub fn get(&self, key: &str) -> Result<Option<Value>, StoreError> {
        let conn = self.conn();
        let text: Option<String> = conn
            .query_row("SELECT result FROM results WHERE key = ?1", params![key], |r| r.get(0))
            .optional()?;
        match text {
            None => Ok(None),
            Some(text) => {
                conn.execute(
                    "UPDATE results SET used = ?1 WHERE key = ?2",
                    params![now_seconds(), key],
                )?;
                Ok(Some(serde_json::from_str(&text)?))
            }
        }
    }

    pub fn put(&self, key: &str, method: &str, result: &Value) -> Result<(), StoreError> {
        let now = now_seconds();
        self.conn().execute(
            "INSERT OR REPLACE INTO results (key, method, created, used, result) VALUES (?1, ?2, ?3, ?3, ?4)",
            params![key, method, now, serde_json::to_string(result)?],
        )?;
        Ok(())
    }

    pub fn len(&self) -> Result<usize, StoreError> {
        let n: i64 = self
            .conn()
            .query_row("SELECT COUNT(*) FROM results", [], |r| r.get(0))?;
        Ok(usize::try_from(n).unwrap_or(0))
    }

    pub fn is_empty(&self) -> Result<bool, StoreError> {
        Ok(self.len()? == 0)
    }

    /// Keep the `keep` most recently used entries and delete the rest; returns how many were deleted.
    pub fn prune(&self, keep: usize) -> Result<usize, StoreError> {
        let keep = i64::try_from(keep).unwrap_or(i64::MAX);
        let deleted = self.conn().execute(
            "DELETE FROM results WHERE key NOT IN (SELECT key FROM results ORDER BY used DESC, created DESC LIMIT ?1)",
            params![keep],
        )?;
        Ok(deleted)
    }

    pub fn clear(&self) -> Result<(), StoreError> {
        self.conn().execute("DELETE FROM results", [])?;
        Ok(())
    }

    /// All entries, oldest first (for export and tests).
    pub fn entries(&self) -> Result<Vec<CacheEntry>, StoreError> {
        let conn = self.conn();
        let mut stmt = conn.prepare("SELECT key, method, result FROM results ORDER BY created, key")?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (key, method, text) = row?;
            out.push(CacheEntry {
                key,
                method,
                result: serde_json::from_str(&text)?,
            });
        }
        Ok(out)
    }
}
