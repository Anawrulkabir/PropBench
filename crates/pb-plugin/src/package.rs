//! Signed plug-in packages (README §2f): a folder with `plugin.toml`, the entry point, its files, `SHA256SUMS` (the
//! SHA-256 of every other file) and `plugin.minisig`, a minisign signature of `SHA256SUMS`.
//!
//! Verification recomputes the listing from the folder and requires it to equal `SHA256SUMS` byte for byte, so an
//! added, removed or changed file is detected; then checks the signature against the trusted keys. The package
//! digest (SHA-256 of `SHA256SUMS`) identifies exactly what the user approved.

use std::collections::BTreeMap;
use std::io::Cursor;
use std::path::{Path, PathBuf};

use minisign::{KeyPair, PublicKey, PublicKeyBox, SecretKey, SecretKeyBox, SignatureBox};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::PluginError;
use crate::manifest::{MANIFEST, Manifest};

pub const SUMS: &str = "SHA256SUMS";
pub const SIGNATURE: &str = "plugin.minisig";
const MAX_FILES: usize = 10_000;
const CACHE_DIRS: [&str; 2] = ["__pycache__", ".pytest_cache"];

/// Who signed a package.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", content = "key", rename_all = "lowercase")]
pub enum Signer {
    /// Signed by this trusted key (minisign key id, hex).
    Trusted(String),
    /// Signed, but not by a trusted key.
    Untrusted(String),
    Unsigned,
}

/// A checked package: its manifest, digest, signer and file hashes.
#[derive(Debug, Clone, Serialize)]
pub struct Package {
    pub dir: PathBuf,
    pub manifest: Manifest,
    pub digest: String,
    pub signer: Signer,
    #[serde(skip)]
    pub files: BTreeMap<String, String>,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

pub fn sha256(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

/// Every regular file below `dir` except the listing and signature, as `relative/path → sha256`. Symbolic links are
/// refused: a package must not point outside itself.
pub fn hash_files(dir: &Path) -> Result<BTreeMap<String, String>, PluginError> {
    let mut out = BTreeMap::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let entries = std::fs::read_dir(&d).map_err(|e| PluginError::io(&d, e))?;
        for entry in entries {
            let entry = entry.map_err(|e| PluginError::io(&d, e))?;
            let path = entry.path();
            let kind = entry.file_type().map_err(|e| PluginError::io(&path, e))?;
            let rel = path
                .strip_prefix(dir)
                .map_err(|_| PluginError::Package(format!("{} is outside the package", path.display())))?
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/");
            if kind.is_symlink() {
                return Err(PluginError::Package(format!("{rel} is a symbolic link")));
            } else if kind.is_dir() {
                // caches of tools run in the folder; never executed (Python plug-ins run with a separate
                // pycache_prefix), so not part of the package
                if !CACHE_DIRS.contains(&entry.file_name().to_string_lossy().as_ref()) {
                    stack.push(path);
                }
            } else if rel != SUMS && rel != SIGNATURE {
                if rel.contains(['\n', '\r']) {
                    return Err(PluginError::Package(format!("invalid file name {rel:?}")));
                }
                let bytes = std::fs::read(&path).map_err(|e| PluginError::io(&path, e))?;
                out.insert(rel, sha256(&bytes));
                if out.len() > MAX_FILES {
                    return Err(PluginError::Package(format!("more than {MAX_FILES} files")));
                }
            }
        }
    }
    Ok(out)
}

/// The text of `SHA256SUMS` for these hashes (sorted, `sha256  path` per line, as `sha256sum` writes it).
pub fn listing(files: &BTreeMap<String, String>) -> String {
    files.iter().map(|(path, sum)| format!("{sum}  {path}\n")).collect()
}

/// Write `SHA256SUMS` and, with a key, `plugin.minisig` (for plug-in authors: `propbench plugin sign`).
pub fn sign(dir: &Path, key: Option<&SecretKey>) -> Result<String, PluginError> {
    let manifest = Manifest::load(dir)?;
    if !dir.join(&manifest.entry).is_file() {
        return Err(PluginError::Package(format!("entry {} is missing", manifest.entry)));
    }
    let text = listing(&hash_files(dir)?);
    write(&dir.join(SUMS), text.as_bytes())?;
    let sig_path = dir.join(SIGNATURE);
    match key {
        Some(key) => {
            let comment = format!("{} {}", manifest.id, manifest.version);
            let sig = minisign::sign(None, key, Cursor::new(text.as_bytes()), Some(&comment), None)
                .map_err(|e| PluginError::Signature(e.to_string()))?;
            write(&sig_path, sig.into_string().as_bytes())?;
        }
        None if sig_path.exists() => std::fs::remove_file(&sig_path).map_err(|e| PluginError::io(&sig_path, e))?,
        None => {}
    }
    Ok(sha256(text.as_bytes()))
}

fn write(path: &Path, bytes: &[u8]) -> Result<(), PluginError> {
    std::fs::write(path, bytes).map_err(|e| PluginError::io(path, e))
}

/// Check a package folder: manifest, listing and signature.
pub fn verify(dir: &Path, trusted: &[PublicKey]) -> Result<Package, PluginError> {
    let manifest = Manifest::load(dir)?;
    let files = hash_files(dir)?;
    if !files.contains_key(&manifest.entry) {
        return Err(PluginError::Package(format!("entry {} is missing", manifest.entry)));
    }
    let sums_path = dir.join(SUMS);
    let sums = std::fs::read_to_string(&sums_path).map_err(|_| {
        PluginError::Package(format!(
            "{SUMS} is missing (sign the package with `propbench plugin sign`)"
        ))
    })?;
    if sums != listing(&files) {
        return Err(PluginError::Package(format!(
            "the files do not match {SUMS}: the package was changed after signing"
        )));
    }
    let sig_path = dir.join(SIGNATURE);
    let signer = if sig_path.exists() {
        let text = std::fs::read_to_string(&sig_path).map_err(|e| PluginError::io(&sig_path, e))?;
        let sig = SignatureBox::from_string(&text).map_err(|e| PluginError::Signature(e.to_string()))?;
        let id = key_id(sig.keynum());
        match trusted.iter().find(|k| key_id(k.keynum()) == id) {
            Some(key) => {
                minisign::verify(key, &sig, Cursor::new(sums.as_bytes()), true, false, false)
                    .map_err(|e| PluginError::Signature(format!("signature by {id} does not verify: {e}")))?;
                Signer::Trusted(id)
            }
            None => Signer::Untrusted(id),
        }
    } else {
        Signer::Unsigned
    };
    Ok(Package {
        dir: dir.to_path_buf(),
        manifest,
        digest: sha256(sums.as_bytes()),
        signer,
        files,
    })
}

/// Read a file of a verified package, checking it still has the hash that was verified.
pub fn read_verified(package: &Package, rel: &str) -> Result<Vec<u8>, PluginError> {
    let expected = package
        .files
        .get(rel)
        .ok_or_else(|| PluginError::Package(format!("{rel} is not part of the package")))?;
    let path = package.dir.join(rel);
    let bytes = std::fs::read(&path).map_err(|e| PluginError::io(&path, e))?;
    if &sha256(&bytes) != expected {
        return Err(PluginError::Package(format!("{rel} changed after verification")));
    }
    Ok(bytes)
}

pub fn key_id(keynum: &[u8]) -> String {
    keynum.iter().rev().map(|b| format!("{b:02X}")).collect()
}

/// A minisign public key from its file text (`untrusted comment` line plus key) or the bare base64 key line.
pub fn public_key(text: &str) -> Result<PublicKey, PluginError> {
    let text = text.trim();
    let key = if text.contains('\n') {
        PublicKeyBox::from_string(text).and_then(PublicKeyBox::into_public_key)
    } else {
        PublicKey::from_base64(text)
    };
    key.map_err(|e| PluginError::Signature(format!("invalid public key: {e}")))
}

/// A new key pair for signing plug-ins: (public key file text, unencrypted secret key file text). Authors keep the
/// secret key themselves; PropBench never stores it.
pub fn generate_keypair() -> Result<(String, String), PluginError> {
    let kp = KeyPair::generate_unencrypted_keypair().map_err(|e| PluginError::Signature(e.to_string()))?;
    let pk = kp
        .pk
        .to_box()
        .map_err(|e| PluginError::Signature(e.to_string()))?
        .into_string();
    let sk = kp
        .sk
        .to_box(None)
        .map_err(|e| PluginError::Signature(e.to_string()))?
        .into_string();
    Ok((pk, sk))
}

pub fn secret_key(text: &str) -> Result<SecretKey, PluginError> {
    SecretKeyBox::from_string(text)
        .and_then(SecretKeyBox::into_unencrypted_secret_key)
        .map_err(|e| PluginError::Signature(format!("invalid secret key: {e}")))
}

/// The manifest file name, re-exported for callers building packages.
pub fn manifest_path(dir: &Path) -> PathBuf {
    dir.join(MANIFEST)
}
