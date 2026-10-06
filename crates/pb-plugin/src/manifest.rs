//! `plugin.toml` (README §2f): id, version, required app API version, entry point and permissions.
//!
//! Permissions are explicit and default to nothing: no network, no GPU, no folder, the default time and memory
//! limits. Folders are named relative to the user's project folder (`read = ["data"]`, `write = ["out"]`); absolute
//! paths and `..` are refused, so a plug-in can never name a folder outside the project.

use std::path::{Component, Path};

use serde::{Deserialize, Serialize};

use crate::PluginError;

/// The plug-in API this host implements. A plug-in needing a newer one is refused.
pub const API_VERSION: u32 = 1;
pub const MANIFEST: &str = "plugin.toml";
const MAX_TIME_S: f64 = 24.0 * 3600.0;
const MAX_MEMORY_MB: u64 = 64 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Kind {
    Model,
    Backend,
    Importer,
    Exporter,
    Analysis,
    PlotType,
    ReportTemplate,
    DataSource,
    AiTool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Runtime {
    /// WebAssembly in wasmtime (binary `.wasm` or text `.wat`): no access to anything not declared (recommended for
    /// third-party plug-ins).
    Wasm,
    /// Python in the project environment, in a separate process with time and memory limits.
    Python,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Permissions {
    #[serde(default)]
    pub network: bool,
    #[serde(default)]
    pub gpu: bool,
    /// Folders of the project the plug-in may read.
    #[serde(default)]
    pub read: Vec<String>,
    /// Folders of the project the plug-in may read and write.
    #[serde(default)]
    pub write: Vec<String>,
    #[serde(default = "default_time")]
    pub time_s: f64,
    #[serde(default = "default_memory")]
    pub memory_mb: u64,
}

fn default_time() -> f64 {
    60.0
}
fn default_memory() -> u64 {
    512
}

impl Default for Permissions {
    fn default() -> Self {
        Permissions {
            network: false,
            gpu: false,
            read: vec![],
            write: vec![],
            time_s: default_time(),
            memory_mb: default_memory(),
        }
    }
}

impl Permissions {
    /// One line per permission, as shown to the user for approval.
    pub fn describe(&self) -> Vec<String> {
        let mut out = vec![];
        out.push(if self.network {
            "network access".into()
        } else {
            "no network access".into()
        });
        if self.gpu {
            out.push("GPU".into());
        }
        for f in &self.read {
            out.push(format!("read the project folder {f}/"));
        }
        for f in &self.write {
            out.push(format!("read and write the project folder {f}/"));
        }
        if self.read.is_empty() && self.write.is_empty() {
            out.push("no file access".into());
        }
        out.push(format!("at most {} s and {} MB per run", self.time_s, self.memory_mb));
        out
    }
}

/// A published value the plug-in must reproduce (check-value harness, README §2f "verified").
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Check {
    pub temperature: f64,
    #[serde(default)]
    pub molar_density: f64,
    pub expected: f64,
    pub rel_tol: f64,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    #[serde(default = "one")]
    pub schema: u32,
    pub id: String,
    pub name: String,
    pub version: String,
    pub api: u32,
    pub kind: Kind,
    pub runtime: Runtime,
    pub entry: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub license: String,
    #[serde(default)]
    pub authors: Vec<String>,
    /// Publication(s) the method is implemented from.
    #[serde(default)]
    pub reference: String,
    #[serde(default)]
    pub fluid: String,
    #[serde(default)]
    pub quantity: String,
    #[serde(default)]
    pub permissions: Permissions,
    #[serde(default, rename = "check")]
    pub checks: Vec<Check>,
}

fn one() -> u32 {
    1
}

impl Manifest {
    pub fn parse(text: &str) -> Result<Manifest, PluginError> {
        let m: Manifest = toml::from_str(text).map_err(|e| PluginError::Manifest(e.to_string()))?;
        m.validate()?;
        Ok(m)
    }

    pub fn load(dir: &Path) -> Result<Manifest, PluginError> {
        let path = dir.join(MANIFEST);
        let text = std::fs::read_to_string(&path).map_err(|e| PluginError::io(&path, e))?;
        Manifest::parse(&text)
    }

    pub fn validate(&self) -> Result<(), PluginError> {
        let bad = |msg: String| Err(PluginError::Manifest(msg));
        if self.schema != 1 {
            return bad(format!("unknown manifest schema {}", self.schema));
        }
        if self.id.is_empty()
            || self.id.len() > 64
            || !self
                .id
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_')
            || self.id.starts_with(['-', '_'])
        {
            return bad(format!(
                "invalid id {:?} (lower-case letters, digits, - and _)",
                self.id
            ));
        }
        if self.version.is_empty() || self.name.is_empty() {
            return bad("name and version are required".into());
        }
        if self.api == 0 || self.api > API_VERSION {
            return bad(format!(
                "{} needs plug-in API {} (this PropBench provides {API_VERSION})",
                self.id, self.api
            ));
        }
        relative(&self.entry).map_err(|e| PluginError::Manifest(format!("entry: {e}")))?;
        let want: &[&str] = match self.runtime {
            Runtime::Wasm => &[".wasm", ".wat"],
            Runtime::Python => &[".py"],
        };
        if !want.iter().any(|w| self.entry.ends_with(w)) {
            return bad(format!(
                "entry of a {:?} plug-in must be a {} file",
                self.runtime,
                want.join(" or ")
            ));
        }
        let p = &self.permissions;
        if !(p.time_s > 0.0 && p.time_s <= MAX_TIME_S) {
            return bad(format!("time_s must be in (0, {MAX_TIME_S}]"));
        }
        if p.memory_mb == 0 || p.memory_mb > MAX_MEMORY_MB {
            return bad(format!("memory_mb must be in [1, {MAX_MEMORY_MB}]"));
        }
        for f in p.read.iter().chain(&p.write) {
            relative(f).map_err(|e| PluginError::Manifest(format!("folder {f:?}: {e}")))?;
        }
        if self.runtime == Runtime::Wasm && (p.network || p.gpu) {
            return bad("WASM plug-ins cannot have network or GPU access in plug-in API 1".into());
        }
        for c in &self.checks {
            if !(c.temperature > 0.0 && c.molar_density >= 0.0 && c.rel_tol > 0.0 && c.expected.is_finite()) {
                return bad(format!("invalid check value {c:?}"));
            }
            if c.source.trim().is_empty() {
                return bad("every check value needs its published source".into());
            }
        }
        Ok(())
    }
}

/// A plain relative path with no `..`, root or prefix.
pub(crate) fn relative(path: &str) -> Result<(), String> {
    if path.is_empty() {
        return Err("empty path".into());
    }
    if path.contains('\\') || path.contains(':') {
        return Err("use / as separator and no drive letters".into());
    }
    for c in Path::new(path).components() {
        match c {
            Component::Normal(_) => {}
            Component::CurDir => {}
            _ => return Err("must be relative and stay inside its folder".into()),
        }
    }
    Ok(())
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    const OK: &str = r#"
id = "demo"
name = "Demo"
version = "1.0.0"
api = 1
kind = "model"
runtime = "wasm"
entry = "demo.wasm"
[permissions]
read = ["data"]
"#;

    #[test]
    fn parses_and_defaults_to_nothing() {
        let m = Manifest::parse(OK).unwrap();
        assert!(!m.permissions.network && m.permissions.write.is_empty());
        assert_eq!(m.permissions.read, ["data"]);
        assert!(m.permissions.describe().contains(&"no network access".to_string()));
    }

    #[test]
    fn refuses_escaping_folders_and_bad_fields() {
        for (from, to) in [
            (r#"read = ["data"]"#, r#"read = ["../home"]"#),
            (r#"read = ["data"]"#, r#"read = ["/etc"]"#),
            (r#"read = ["data"]"#, r#"write = ["C:/Users"]"#),
            (r#"read = ["data"]"#, "network = true"),
            (r#"read = ["data"]"#, "shell = true"),
            ("api = 1", "api = 2"),
            (r#"entry = "demo.wasm""#, r#"entry = "../demo.wasm""#),
            (r#"entry = "demo.wasm""#, r#"entry = "demo.py""#),
            (r#"id = "demo""#, r#"id = "../x""#),
        ] {
            let text = OK.replace(from, to);
            assert!(Manifest::parse(&text).is_err(), "accepted {to}");
        }
    }
}
