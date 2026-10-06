//! PropBench plug-in host (README §2f; CLAUDE.md plug-in rules).
//!
//! A plug-in is a folder with `plugin.toml` (id, version, API version, entry point, permissions), its entry point
//! and a signed file listing (`package`). Installing copies a verified package into the plug-ins folder of the app
//! data folder; it does not enable it. The user approves the declared permissions (`PluginHost::approve`), and that
//! approval is bound to the package digest: any change to the package withdraws it. Every run verifies the package
//! again and grants exactly the approved permissions, nothing undeclared.
//!
//! WASM plug-ins run here (`wasm`); Python plug-ins run in the project environment through the worker
//! (`PluginHost::python_request` prepares the request the shell sends).

pub mod manifest;
pub mod package;
pub mod wasm;

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

pub use manifest::{API_VERSION, Check, Kind, Manifest, Permissions, Runtime};
pub use package::{Package, Signer};

#[derive(Debug, thiserror::Error)]
pub enum PluginError {
    #[error("plugin.toml: {0}")]
    Manifest(String),
    #[error("plug-in package: {0}")]
    Package(String),
    #[error("signature: {0}")]
    Signature(String),
    #[error("permission denied: {0}")]
    Permission(String),
    #[error("plug-in {0} is not installed")]
    NotFound(String),
    #[error("plug-in {0} is not approved: approve its permissions first")]
    NotApproved(String),
    #[error("plug-in {0}")]
    Limit(String),
    #[error("WebAssembly: {0}")]
    Wasm(String),
    #[error("{path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
}

impl PluginError {
    pub(crate) fn io(path: &Path, source: std::io::Error) -> PluginError {
        PluginError::Io {
            path: path.to_path_buf(),
            source,
        }
    }
}

const APPROVALS: &str = "approvals.json";
const TRUSTED: &str = "trusted_keys.txt";

/// The user's approval of one package: its digest and the permissions shown at the time.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Approval {
    pub version: String,
    pub digest: String,
    pub permissions: Permissions,
    pub signer: String,
    pub time: u64,
}

/// An installed plug-in as listed for the user.
#[derive(Debug, Clone, Serialize)]
pub struct Installed {
    pub manifest: Manifest,
    pub digest: String,
    pub signer: Signer,
    pub approved: bool,
    pub permissions: Vec<String>,
    /// Why it cannot be used (package changed, signature invalid, ...), if so.
    pub problem: Option<String>,
}

/// One check value of the harness.
#[derive(Debug, Clone, Serialize)]
pub struct CheckResult {
    pub check: Check,
    pub value: f64,
    pub rel_dev: f64,
    pub pass: bool,
}

/// The plug-ins folder (`<app data>/plugins`): one folder per plug-in id, the approvals and the trusted keys.
pub struct PluginHost {
    root: PathBuf,
}

impl PluginHost {
    pub fn new(root: impl Into<PathBuf>) -> PluginHost {
        PluginHost { root: root.into() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Keys whose signatures mark a plug-in as trusted (the registry's key and any the user added).
    pub fn trusted_keys(&self) -> Result<Vec<minisign::PublicKey>, PluginError> {
        let path = self.root.join(TRUSTED);
        let text = match std::fs::read_to_string(&path) {
            Ok(t) => t,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(vec![]),
            Err(e) => return Err(PluginError::io(&path, e)),
        };
        text.lines()
            .map(str::trim)
            .filter(|l| !l.is_empty() && !l.starts_with('#') && !l.starts_with("untrusted comment"))
            .map(package::public_key)
            .collect()
    }

    /// Trust a minisign public key; returns its key id.
    pub fn trust_key(&self, key: &str) -> Result<String, PluginError> {
        let pk = package::public_key(key)?;
        let id = package::key_id(pk.keynum());
        let path = self.root.join(TRUSTED);
        let mut text = std::fs::read_to_string(&path).unwrap_or_default();
        if !self.trusted_keys()?.iter().any(|k| package::key_id(k.keynum()) == id) {
            text.push_str(&format!("# key {id}\n{}\n", pk.to_base64()));
            self.write_atomic(&path, text.as_bytes())?;
        }
        Ok(id)
    }

    /// Check a package folder without installing it (what the install dialog shows).
    pub fn inspect(&self, dir: &Path) -> Result<Package, PluginError> {
        package::verify(dir, &self.trusted_keys()?)
    }

    /// Copy a verified package into the plug-ins folder (replacing an older version). Not yet approved.
    pub fn install(&self, src: &Path) -> Result<Package, PluginError> {
        let checked = self.inspect(src)?;
        if let Signer::Untrusted(id) = &checked.signer {
            return Err(PluginError::Signature(format!(
                "signed by key {id}, which is not trusted; add the author's public key first or use an unsigned local package"
            )));
        }
        let id = checked.manifest.id.clone();
        std::fs::create_dir_all(&self.root).map_err(|e| PluginError::io(&self.root, e))?;
        let tmp = self.root.join(format!(".{id}.installing"));
        if tmp.exists() {
            std::fs::remove_dir_all(&tmp).map_err(|e| PluginError::io(&tmp, e))?;
        }
        for rel in checked
            .files
            .keys()
            .map(String::as_str)
            .chain([package::SUMS, package::SIGNATURE])
        {
            let from = src.join(rel);
            if !from.exists() {
                continue;
            }
            let to = tmp.join(rel);
            if let Some(parent) = to.parent() {
                std::fs::create_dir_all(parent).map_err(|e| PluginError::io(parent, e))?;
            }
            std::fs::copy(&from, &to).map_err(|e| PluginError::io(&from, e))?;
        }
        let installed = package::verify(&tmp, &self.trusted_keys()?)?;
        if installed.digest != checked.digest {
            let _ = std::fs::remove_dir_all(&tmp);
            return Err(PluginError::Package(
                "the package changed while it was installed".into(),
            ));
        }
        let dest = self.root.join(&id);
        if dest.exists() {
            std::fs::remove_dir_all(&dest).map_err(|e| PluginError::io(&dest, e))?;
        }
        std::fs::rename(&tmp, &dest).map_err(|e| PluginError::io(&dest, e))?;
        package::verify(&dest, &self.trusted_keys()?)
    }

    pub fn remove(&self, id: &str) -> Result<(), PluginError> {
        let dir = self.dir(id)?;
        std::fs::remove_dir_all(&dir).map_err(|e| PluginError::io(&dir, e))?;
        let mut approvals = self.approvals()?;
        if approvals.remove(id).is_some() {
            self.save_approvals(&approvals)?;
        }
        Ok(())
    }

    fn dir(&self, id: &str) -> Result<PathBuf, PluginError> {
        manifest::relative(id).map_err(|_| PluginError::NotFound(id.into()))?;
        let dir = self.root.join(id);
        if id.contains('/') || !dir.join(manifest::MANIFEST).is_file() {
            return Err(PluginError::NotFound(id.into()));
        }
        Ok(dir)
    }

    pub fn approvals(&self) -> Result<BTreeMap<String, Approval>, PluginError> {
        let path = self.root.join(APPROVALS);
        match std::fs::read_to_string(&path) {
            Ok(text) => serde_json::from_str(&text).map_err(|e| PluginError::Package(format!("{APPROVALS}: {e}"))),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(BTreeMap::new()),
            Err(e) => Err(PluginError::io(&path, e)),
        }
    }

    fn save_approvals(&self, approvals: &BTreeMap<String, Approval>) -> Result<(), PluginError> {
        let text = serde_json::to_string_pretty(approvals).map_err(|e| PluginError::Package(e.to_string()))?;
        self.write_atomic(&self.root.join(APPROVALS), text.as_bytes())
    }

    fn write_atomic(&self, path: &Path, bytes: &[u8]) -> Result<(), PluginError> {
        std::fs::create_dir_all(&self.root).map_err(|e| PluginError::io(&self.root, e))?;
        let tmp = path.with_extension("tmp");
        std::fs::write(&tmp, bytes).map_err(|e| PluginError::io(&tmp, e))?;
        std::fs::rename(&tmp, path).map_err(|e| PluginError::io(path, e))
    }

    /// Approve the permissions of an installed plug-in, as shown to the user. `digest` must be the digest the user
    /// saw; an unsigned package needs `allow_unsigned` (local development).
    pub fn approve(&self, id: &str, digest: &str, allow_unsigned: bool) -> Result<Approval, PluginError> {
        let pkg = package::verify(&self.dir(id)?, &self.trusted_keys()?)?;
        if pkg.digest != digest {
            return Err(PluginError::Package(
                "the package is not the one that was shown for approval".into(),
            ));
        }
        let signer = match &pkg.signer {
            Signer::Trusted(k) => k.clone(),
            Signer::Unsigned if allow_unsigned => "unsigned".into(),
            Signer::Unsigned => return Err(PluginError::Signature("the package is unsigned".into())),
            Signer::Untrusted(k) => return Err(PluginError::Signature(format!("key {k} is not trusted"))),
        };
        let time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs());
        let approval = Approval {
            version: pkg.manifest.version.clone(),
            digest: pkg.digest,
            permissions: pkg.manifest.permissions,
            signer,
            time,
        };
        let mut approvals = self.approvals()?;
        approvals.insert(id.to_string(), approval.clone());
        self.save_approvals(&approvals)?;
        Ok(approval)
    }

    pub fn revoke(&self, id: &str) -> Result<(), PluginError> {
        let mut approvals = self.approvals()?;
        if approvals.remove(id).is_some() {
            self.save_approvals(&approvals)?;
        }
        Ok(())
    }

    pub fn list(&self) -> Result<Vec<Installed>, PluginError> {
        let mut out = vec![];
        let entries = match std::fs::read_dir(&self.root) {
            Ok(e) => e,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(out),
            Err(e) => return Err(PluginError::io(&self.root, e)),
        };
        let approvals = self.approvals()?;
        let trusted = self.trusted_keys()?;
        let mut dirs: Vec<PathBuf> = entries
            .filter_map(Result::ok)
            .map(|e| e.path())
            .filter(|p| {
                p.join(manifest::MANIFEST).is_file()
                    && !p.file_name().is_some_and(|n| n.to_string_lossy().starts_with('.'))
            })
            .collect();
        dirs.sort();
        for dir in dirs {
            let Ok(manifest) = Manifest::load(&dir) else { continue };
            let item = match package::verify(&dir, &trusted) {
                Ok(pkg) => {
                    let approved = approvals
                        .get(&manifest.id)
                        .is_some_and(|a| a.digest == pkg.digest && a.permissions == manifest.permissions);
                    Installed {
                        permissions: manifest.permissions.describe(),
                        manifest,
                        digest: pkg.digest,
                        signer: pkg.signer,
                        approved,
                        problem: None,
                    }
                }
                Err(e) => Installed {
                    permissions: manifest.permissions.describe(),
                    manifest,
                    digest: String::new(),
                    signer: Signer::Unsigned,
                    approved: false,
                    problem: Some(e.to_string()),
                },
            };
            out.push(item);
        }
        Ok(out)
    }

    /// Verify an installed plug-in and its approval; the package and the permissions it may use.
    pub fn load(&self, id: &str) -> Result<(Package, Permissions), PluginError> {
        let pkg = package::verify(&self.dir(id)?, &self.trusted_keys()?)?;
        let approval = self
            .approvals()?
            .remove(id)
            .ok_or_else(|| PluginError::NotApproved(id.into()))?;
        if approval.digest != pkg.digest || approval.permissions != pkg.manifest.permissions {
            return Err(PluginError::NotApproved(format!(
                "{id} (changed since it was approved)"
            )));
        }
        if matches!(pkg.signer, Signer::Untrusted(_))
            || (pkg.signer == Signer::Unsigned && approval.signer != "unsigned")
        {
            return Err(PluginError::NotApproved(format!("{id} (signature changed)")));
        }
        Ok((pkg, approval.permissions))
    }

    /// Evaluate an approved WASM model plug-in.
    pub fn predict(&self, id: &str, states: &[(f64, f64)]) -> Result<Vec<f64>, PluginError> {
        let (pkg, permissions) = self.load(id)?;
        wasm_model(&pkg)?;
        let bytes = package::read_verified(&pkg, &pkg.manifest.entry)?;
        wasm::predict(&bytes, &permissions, states)
    }

    /// Run an approved WASM tool plug-in with its declared folders of `project`.
    pub fn run(
        &self,
        id: &str,
        project: Option<&Path>,
        stdin: &[u8],
        args: &[String],
    ) -> Result<wasm::Output, PluginError> {
        let (pkg, permissions) = self.load(id)?;
        if pkg.manifest.runtime != Runtime::Wasm {
            return Err(PluginError::Manifest(format!(
                "{id} is a Python plug-in: it runs in the project environment"
            )));
        }
        let bytes = package::read_verified(&pkg, &pkg.manifest.entry)?;
        wasm::run(&bytes, &permissions, project, stdin, args)
    }

    /// The check-value harness: evaluate the plug-in at its published check values. A WASM model plug-in is
    /// checked here; Python plug-ins are checked by the worker (`plugins.check`).
    pub fn check(&self, dir: &Path) -> Result<Vec<CheckResult>, PluginError> {
        let pkg = package::verify(dir, &self.trusted_keys()?)?;
        wasm_model(&pkg)?;
        let bytes = package::read_verified(&pkg, &pkg.manifest.entry)?;
        let states: Vec<(f64, f64)> = pkg
            .manifest
            .checks
            .iter()
            .map(|c| (c.temperature, c.molar_density))
            .collect();
        let values = wasm::predict(&bytes, &pkg.manifest.permissions, &states)?;
        Ok(harness(&pkg.manifest.checks, &values))
    }

    /// What the shell sends to the worker (`plugins.run`) to run an approved Python plug-in: its folder, entry
    /// point and the approved permissions (the worker grants nothing else).
    pub fn python_request(
        &self,
        id: &str,
        project: Option<&Path>,
        method: &str,
        params: Value,
    ) -> Result<Value, PluginError> {
        let (pkg, permissions) = self.load(id)?;
        if pkg.manifest.runtime != Runtime::Python {
            return Err(PluginError::Manifest(format!("{id} is not a Python plug-in")));
        }
        Ok(json!({
            "dir": pkg.dir,
            "id": pkg.manifest.id,
            "entry": pkg.manifest.entry,
            "digest": pkg.digest,
            "permissions": permissions,
            "project_dir": project,
            "method": method,
            "params": params,
        }))
    }
}

fn wasm_model(pkg: &Package) -> Result<(), PluginError> {
    if pkg.manifest.runtime != Runtime::Wasm || pkg.manifest.kind != Kind::Model {
        return Err(PluginError::Manifest(format!(
            "{} is not a WASM model plug-in",
            pkg.manifest.id
        )));
    }
    Ok(())
}

/// Compare values with check values: relative deviation (model − expected)/expected within `rel_tol`.
pub fn harness(checks: &[Check], values: &[f64]) -> Vec<CheckResult> {
    checks
        .iter()
        .zip(values)
        .map(|(c, &v)| {
            let rel_dev = (v - c.expected) / c.expected;
            CheckResult {
                check: c.clone(),
                value: v,
                rel_dev,
                pass: rel_dev.is_finite() && rel_dev.abs() <= c.rel_tol,
            }
        })
        .collect()
}
