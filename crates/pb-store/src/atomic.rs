use std::fs;
use std::path::{Path, PathBuf};

use crate::StoreError;

/// The temporary file a save writes before renaming it over `path`: same folder (so the rename stays on one
/// file system and is atomic), hidden, with the process id so two processes never share it.
pub fn temp_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "project.pbp".into());
    path.with_file_name(format!(".{name}.{}.tmp", std::process::id()))
}

/// Write `path` atomically: `write` fills a temporary file next to it, which is flushed to disk and renamed over
/// `path` (on Windows `rename` replaces an existing file too). On any error the temporary file is removed and
/// `path` is left as it was.
pub fn atomic_write_with<F>(path: &Path, write: F) -> Result<(), StoreError>
where
    F: FnOnce(&Path) -> Result<(), StoreError>,
{
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        fs::create_dir_all(parent)?;
    }
    let tmp = temp_path(path);
    let _ = fs::remove_file(&tmp);
    let result = write(&tmp).and_then(|()| {
        fs::File::open(&tmp)?.sync_all()?;
        fs::rename(&tmp, path)?;
        Ok(())
    });
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}
