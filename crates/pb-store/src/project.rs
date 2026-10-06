use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{Connection, OpenFlags, Transaction, params};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{StoreError, atomic_write_with, temp_path};

/// Value of the `format` meta entry of every project file.
pub const FORMAT: &str = "propbench-project";
/// SQLite `application_id` of project files ("PBPJ").
pub const APPLICATION_ID: i64 = 0x5042_504A;
/// Current project schema. Every change bumps it and appends a migration to `MIGRATIONS`.
pub const SCHEMA_VERSION: i64 = 1;

/// Schema of version 1.
const SCHEMA_V1: &str = "
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE datasets (
    position INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    fluid TEXT NOT NULL,
    quantity TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE documents (key TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE snapshots (id INTEGER PRIMARY KEY, label TEXT NOT NULL, created INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE audit (id INTEGER PRIMARY KEY, time INTEGER NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
";

/// `MIGRATIONS[i]` upgrades a file from schema `i + 1` to `i + 2`, inside one transaction.
type Migration = fn(&Transaction<'_>) -> Result<(), rusqlite::Error>;
const MIGRATIONS: &[Migration] = &[];

/// Seconds since the Unix epoch (UTC); 0 if the clock is before 1970.
pub fn now_seconds() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| i64::try_from(d.as_secs()).unwrap_or(i64::MAX))
        .unwrap_or(0)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Meta {
    pub name: String,
    /// Seconds since the Unix epoch.
    pub created: i64,
    pub modified: i64,
    /// Version of PropBench that last saved the file.
    pub app_version: String,
    /// Schema of the file as read (always [`SCHEMA_VERSION`] after a save).
    #[serde(default = "current_schema")]
    pub schema_version: i64,
}

fn current_schema() -> i64 {
    SCHEMA_VERSION
}

impl Default for Meta {
    fn default() -> Self {
        let now = now_seconds();
        Self {
            name: "Untitled project".into(),
            created: now,
            modified: now,
            app_version: String::new(),
            schema_version: SCHEMA_VERSION,
        }
    }
}

/// One dataset: the worker's dataset JSON (`data`, SI units) with its name, fluid and quantity as columns.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DatasetRecord {
    pub name: String,
    pub data: Value,
}

impl DatasetRecord {
    fn field(&self, key: &str) -> String {
        self.data
            .get(key)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned()
    }
}

/// A named copy of the datasets and documents at one moment.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Snapshot {
    pub id: i64,
    pub label: String,
    pub created: i64,
    pub datasets: Vec<DatasetRecord>,
    pub documents: BTreeMap<String, Value>,
}

/// One line of the audit log (README §4: who changed what, e.g. "selection rule locked").
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AuditEntry {
    pub time: i64,
    pub action: String,
    pub detail: String,
}

/// The whole content of a project file. It is plain data: the UI sends it, `save` writes it, `load` reads it.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct Project {
    pub meta: Meta,
    #[serde(default)]
    pub datasets: Vec<DatasetRecord>,
    #[serde(default)]
    pub documents: BTreeMap<String, Value>,
    #[serde(default)]
    pub snapshots: Vec<Snapshot>,
    #[serde(default)]
    pub audit: Vec<AuditEntry>,
}

impl Project {
    pub fn new(name: &str) -> Self {
        Self {
            meta: Meta {
                name: name.to_owned(),
                ..Meta::default()
            },
            ..Self::default()
        }
    }

    /// Append an audit entry stamped now.
    pub fn log(&mut self, action: &str, detail: &str) {
        self.audit.push(AuditEntry {
            time: now_seconds(),
            action: action.to_owned(),
            detail: detail.to_owned(),
        });
    }

    /// Store the current datasets and documents as a snapshot and return its id.
    pub fn snapshot(&mut self, label: &str) -> i64 {
        let id = self.snapshots.iter().map(|s| s.id).max().unwrap_or(0) + 1;
        self.snapshots.push(Snapshot {
            id,
            label: label.to_owned(),
            created: now_seconds(),
            datasets: self.datasets.clone(),
            documents: self.documents.clone(),
        });
        self.log("snapshot", &format!("{id}: {label}"));
        id
    }

    /// Replace the datasets and documents by those of snapshot `id` (the snapshots themselves are kept).
    pub fn restore(&mut self, id: i64) -> Result<(), StoreError> {
        let snap = self
            .snapshots
            .iter()
            .find(|s| s.id == id)
            .cloned()
            .ok_or_else(|| StoreError::Invalid(format!("no snapshot {id}")))?;
        self.datasets = snap.datasets;
        self.documents = snap.documents;
        self.log("restore", &format!("{id}: {}", snap.label));
        Ok(())
    }

    fn validate(&self) -> Result<(), StoreError> {
        let mut names = BTreeSet::new();
        for d in &self.datasets {
            if d.name.trim().is_empty() {
                return Err(StoreError::Invalid("a dataset has no name".into()));
            }
            if !names.insert(d.name.as_str()) {
                return Err(StoreError::Invalid(format!("dataset name `{}` is used twice", d.name)));
            }
        }
        if self.documents.keys().any(|k| k.trim().is_empty()) {
            return Err(StoreError::Invalid("a document has an empty key".into()));
        }
        Ok(())
    }

    /// Write the project to `path` atomically (temporary file + rename). `meta.modified` and `app_version` are
    /// set by the caller; the schema version written is always [`SCHEMA_VERSION`].
    pub fn save(&self, path: &Path) -> Result<(), StoreError> {
        self.validate()?;
        atomic_write_with(path, |tmp| self.write_new(tmp))
    }

    fn write_new(&self, tmp: &Path) -> Result<(), StoreError> {
        let mut conn = Connection::open(tmp)?;
        conn.execute_batch("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;")?;
        let tx = conn.transaction()?;
        tx.execute_batch(SCHEMA_V1)?;
        tx.execute_batch(&format!(
            "PRAGMA application_id = {APPLICATION_ID}; PRAGMA user_version = {SCHEMA_VERSION};"
        ))?;
        let meta = [
            ("format", FORMAT.to_owned()),
            ("name", self.meta.name.clone()),
            ("created", self.meta.created.to_string()),
            ("modified", self.meta.modified.to_string()),
            ("app_version", self.meta.app_version.clone()),
        ];
        for (key, value) in meta {
            tx.execute("INSERT INTO meta (key, value) VALUES (?1, ?2)", params![key, value])?;
        }
        for (i, d) in self.datasets.iter().enumerate() {
            tx.execute(
                "INSERT INTO datasets (position, name, fluid, quantity, data) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    i64::try_from(i).unwrap_or(i64::MAX),
                    d.name,
                    d.field("fluid"),
                    d.field("quantity"),
                    serde_json::to_string(&d.data)?
                ],
            )?;
        }
        for (key, value) in &self.documents {
            tx.execute(
                "INSERT INTO documents (key, data) VALUES (?1, ?2)",
                params![key, serde_json::to_string(value)?],
            )?;
        }
        for s in &self.snapshots {
            let data = serde_json::json!({ "datasets": s.datasets, "documents": s.documents });
            tx.execute(
                "INSERT INTO snapshots (id, label, created, data) VALUES (?1, ?2, ?3, ?4)",
                params![s.id, s.label, s.created, serde_json::to_string(&data)?],
            )?;
        }
        for a in &self.audit {
            tx.execute(
                "INSERT INTO audit (time, action, detail) VALUES (?1, ?2, ?3)",
                params![a.time, a.action, a.detail],
            )?;
        }
        tx.commit()?;
        conn.close().map_err(|(_, e)| e)?;
        Ok(())
    }

    /// Read a project file. Files of an older schema are migrated in a temporary copy (the file itself is not
    /// changed until the next save); files of a newer schema are refused.
    pub fn load(path: &Path) -> Result<Self, StoreError> {
        let not_a_project = || StoreError::NotAProject {
            path: path.to_path_buf(),
        };
        if !path.is_file() {
            return Err(StoreError::Io(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("{} does not exist", path.display()),
            )));
        }
        let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|_| not_a_project())?;
        let (app_id, version) = header(&conn).map_err(|_| not_a_project())?;
        if app_id != APPLICATION_ID {
            return Err(not_a_project());
        }
        if version > SCHEMA_VERSION {
            return Err(StoreError::TooNew {
                path: path.to_path_buf(),
                found: version,
                supported: SCHEMA_VERSION,
            });
        }
        if version < 1 {
            return Err(not_a_project());
        }
        if version == SCHEMA_VERSION {
            return read(&conn, path, version);
        }
        drop(conn);
        // Older schema: migrate a copy next to the file, read it, remove it.
        let copy = temp_path(path);
        std::fs::copy(path, &copy)?;
        let result = migrate_and_read(&copy, path, version);
        let _ = std::fs::remove_file(&copy);
        result
    }
}

fn header(conn: &Connection) -> Result<(i64, i64), rusqlite::Error> {
    let app_id: i64 = conn.query_row("PRAGMA application_id", [], |r| r.get(0))?;
    let version: i64 = conn.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    Ok((app_id, version))
}

fn migrate_and_read(copy: &Path, original: &Path, from: i64) -> Result<Project, StoreError> {
    let mut conn = Connection::open(copy)?;
    for version in from..SCHEMA_VERSION {
        let index = usize::try_from(version - 1).unwrap_or(usize::MAX);
        let migration = MIGRATIONS.get(index).ok_or_else(|| StoreError::Corrupt {
            path: original.to_path_buf(),
            message: format!("no migration from schema {version}"),
        })?;
        let tx = conn.transaction()?;
        migration(&tx)?;
        tx.execute_batch(&format!("PRAGMA user_version = {};", version + 1))?;
        tx.commit()?;
    }
    read(&conn, original, from)
}

fn read(conn: &Connection, path: &Path, read_version: i64) -> Result<Project, StoreError> {
    let corrupt = |message: String| StoreError::Corrupt {
        path: path.to_path_buf(),
        message,
    };
    let mut meta_rows = BTreeMap::new();
    {
        let mut stmt = conn.prepare("SELECT key, value FROM meta")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
        for row in rows {
            let (k, v) = row?;
            meta_rows.insert(k, v);
        }
    }
    if meta_rows.get("format").map(String::as_str) != Some(FORMAT) {
        return Err(StoreError::NotAProject {
            path: path.to_path_buf(),
        });
    }
    let number = |key: &str| -> Result<i64, StoreError> {
        meta_rows
            .get(key)
            .ok_or_else(|| corrupt(format!("meta entry `{key}` is missing")))?
            .parse()
            .map_err(|_| corrupt(format!("meta entry `{key}` is not a number")))
    };
    let meta = Meta {
        name: meta_rows.get("name").cloned().unwrap_or_default(),
        created: number("created")?,
        modified: number("modified")?,
        app_version: meta_rows.get("app_version").cloned().unwrap_or_default(),
        schema_version: read_version,
    };
    let json = |text: String| serde_json::from_str::<Value>(&text).map_err(|e| corrupt(e.to_string()));

    let mut datasets = Vec::new();
    {
        let mut stmt = conn.prepare("SELECT name, data FROM datasets ORDER BY position")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
        for row in rows {
            let (name, data) = row?;
            datasets.push(DatasetRecord {
                name,
                data: json(data)?,
            });
        }
    }
    let mut documents = BTreeMap::new();
    {
        let mut stmt = conn.prepare("SELECT key, data FROM documents")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
        for row in rows {
            let (key, data) = row?;
            documents.insert(key, json(data)?);
        }
    }
    let mut snapshots = Vec::new();
    {
        let mut stmt = conn.prepare("SELECT id, label, created, data FROM snapshots ORDER BY id")?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, String>(3)?,
            ))
        })?;
        for row in rows {
            let (id, label, created, data) = row?;
            #[derive(Deserialize)]
            struct Content {
                datasets: Vec<DatasetRecord>,
                documents: BTreeMap<String, Value>,
            }
            let content: Content = serde_json::from_str(&data).map_err(|e| corrupt(e.to_string()))?;
            snapshots.push(Snapshot {
                id,
                label,
                created,
                datasets: content.datasets,
                documents: content.documents,
            });
        }
    }
    let mut audit = Vec::new();
    {
        let mut stmt = conn.prepare("SELECT time, action, detail FROM audit ORDER BY id")?;
        let rows = stmt.query_map([], |r| {
            Ok(AuditEntry {
                time: r.get(0)?,
                action: r.get(1)?,
                detail: r.get(2)?,
            })
        })?;
        for row in rows {
            audit.push(row?);
        }
    }
    Ok(Project {
        meta,
        datasets,
        documents,
        snapshots,
        audit,
    })
}
