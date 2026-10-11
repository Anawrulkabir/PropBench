//! Project history in Git (README §4d): a Git-friendly mirror of a project (settings and results as text,
//! datasets as CSV and JSON, the audit log) committed with gitoxide, so no Git installation is needed. The
//! mirror folder is an ordinary Git repository: it can be inspected with any Git tool and pushed to GitHub.

use std::collections::BTreeMap;
use std::path::Path;

use gix::bstr::BString;
use gix::objs::tree::{Entry, EntryKind};
use pb_store::Project;
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum GitError {
    #[error("git error: {0}")]
    Git(String),
    #[error("file error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

fn git(err: impl std::fmt::Display) -> GitError {
    GitError::Git(err.to_string())
}

/// One commit of the history.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct CommitInfo {
    pub id: String,
    pub message: String,
    pub author: String,
    /// Seconds since the Unix epoch.
    pub time: i64,
}

fn safe(name: &str) -> String {
    let s: String = name
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.') {
                c
            } else {
                '_'
            }
        })
        .collect();
    if s.is_empty() || s.starts_with('.') {
        format!("_{s}")
    } else {
        s
    }
}

fn csv_of(data: &Value) -> String {
    let col = |k: &str| data.get(k).and_then(Value::as_array).cloned().unwrap_or_default();
    let (t, p, rho, y, u, ids, phase) = (
        col("temperature"),
        col("pressure"),
        col("molar_density"),
        col("values"),
        col("expanded_uncertainty"),
        col("point_ids"),
        col("phase"),
    );
    let cell = |v: Option<&Value>| match v {
        Some(Value::Null) | None => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(v) => v.to_string(),
    };
    let mut out = String::from("point_id,T_K,p_Pa,rho_mol_m3,value_SI,U_SI,phase\n");
    for i in 0..y.len() {
        let row = [&ids, &t, &p, &rho, &y, &u, &phase].map(|c| cell(c.get(i)));
        out.push_str(&row.join(","));
        out.push('\n');
    }
    out
}

/// The mirror's files (path → content): text that diffs well.
pub fn mirror_files(project: &Project) -> Result<BTreeMap<String, Vec<u8>>, GitError> {
    let mut files = BTreeMap::new();
    let names: Vec<String> = project.datasets.iter().map(|d| format!("- {}", d.name)).collect();
    files.insert(
        "README.md".to_owned(),
        format!(
            "# {}\n\nPropBench project mirror (written by PropBench; the .pbp file is the source).\n\n## Datasets\n\n{}\n",
            project.meta.name,
            names.join("\n")
        )
        .into_bytes(),
    );
    let settings = serde_json::json!({ "meta": project.meta, "documents": project.documents });
    files.insert("project.json".to_owned(), serde_json::to_vec_pretty(&settings)?);
    for d in &project.datasets {
        let stem = safe(&d.name);
        files.insert(format!("datasets/{stem}.csv"), csv_of(&d.data).into_bytes());
        files.insert(format!("datasets/{stem}.json"), serde_json::to_vec_pretty(&d.data)?);
    }
    let audit: Vec<String> = project
        .audit
        .iter()
        .map(|a| format!("{}\t{}\t{}", a.time, a.action, a.detail))
        .collect();
    files.insert("audit.log".to_owned(), (audit.join("\n") + "\n").into_bytes());
    Ok(files)
}

fn write_tree(repo: &gix::Repository, files: &BTreeMap<String, Vec<u8>>) -> Result<gix::ObjectId, GitError> {
    // group by first path component: files here, folders as subtrees
    let mut here: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    let mut folders: BTreeMap<String, BTreeMap<String, Vec<u8>>> = BTreeMap::new();
    for (path, content) in files {
        match path.split_once('/') {
            Some((dir, rest)) => {
                folders
                    .entry(dir.to_owned())
                    .or_default()
                    .insert(rest.to_owned(), content.clone());
            }
            None => {
                here.insert(path.clone(), content.clone());
            }
        }
    }
    let mut entries = Vec::new();
    for (name, content) in here {
        let oid = repo.write_blob(&content).map_err(git)?.detach();
        entries.push(Entry {
            mode: EntryKind::Blob.into(),
            filename: BString::from(name),
            oid,
        });
    }
    for (name, sub) in folders {
        let oid = write_tree(repo, &sub)?;
        entries.push(Entry {
            mode: EntryKind::Tree.into(),
            filename: BString::from(name),
            oid,
        });
    }
    entries.sort();
    let tree = gix::objs::Tree { entries };
    Ok(repo.write_object(&tree).map_err(git)?.detach())
}

fn open_or_init(dir: &Path) -> Result<gix::Repository, GitError> {
    if dir.join(".git").is_dir() {
        gix::open(dir).map_err(git)
    } else {
        std::fs::create_dir_all(dir)?;
        gix::init(dir).map_err(git)
    }
}

/// Write the mirror of `project` into `dir` and commit it. Returns `None` when nothing changed.
pub fn commit(
    dir: &Path,
    project: &Project,
    message: &str,
    name: &str,
    email: &str,
) -> Result<Option<CommitInfo>, GitError> {
    let repo = open_or_init(dir)?;
    let files = mirror_files(project)?;
    // the working tree shows the same files (stale dataset files removed)
    let datasets = dir.join("datasets");
    if datasets.is_dir() {
        for entry in std::fs::read_dir(&datasets)? {
            let path = entry?.path();
            let rel = format!(
                "datasets/{}",
                path.file_name().map(|n| n.to_string_lossy()).unwrap_or_default()
            );
            if !files.contains_key(&rel) {
                std::fs::remove_file(path)?;
            }
        }
    }
    for (path, content) in &files {
        let target = dir.join(path);
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(target, content)?;
    }
    let tree = write_tree(&repo, &files)?;
    let parent = repo.head_id().ok().map(|id| id.detach());
    if let Some(p) = parent {
        let head_tree = repo.find_commit(p).map_err(git)?.tree_id().map_err(git)?.detach();
        if head_tree == tree {
            return Ok(None);
        }
    }
    let now = pb_store::now_seconds();
    let sig = gix::actor::Signature {
        name: name.into(),
        email: email.into(),
        time: gix::date::Time::new(now, 0),
    };
    let mut buf = gix::date::parse::TimeBuf::default();
    let sig_ref = sig.to_ref(&mut buf);
    let id = repo
        .commit_as(sig_ref, sig_ref, "HEAD", message, tree, parent)
        .map_err(git)?
        .detach();
    Ok(Some(CommitInfo {
        id: id.to_string(),
        message: message.to_owned(),
        author: name.to_owned(),
        time: now,
    }))
}

/// The most recent commits, newest first.
pub fn history(dir: &Path, limit: usize) -> Result<Vec<CommitInfo>, GitError> {
    if !dir.join(".git").is_dir() {
        return Ok(Vec::new());
    }
    let repo = gix::open(dir).map_err(git)?;
    let Ok(head) = repo.head_id() else {
        return Ok(Vec::new());
    };
    let mut out = Vec::new();
    for info in head.ancestors().all().map_err(git)?.take(limit) {
        let info = info.map_err(git)?;
        let commit = repo.find_commit(info.id).map_err(git)?;
        let decoded = commit.decode().map_err(git)?;
        let author = decoded.author().map_err(git)?;
        out.push(CommitInfo {
            id: info.id.to_string(),
            message: decoded.message.to_string().trim_end().to_owned(),
            author: author.name.to_string(),
            time: author.time().map(|t| t.seconds).unwrap_or(0),
        });
    }
    Ok(out)
}
