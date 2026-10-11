//! README M4c acceptance: a sandboxed plug-in cannot read outside its declared folder; the template plug-in passes
//! the check-value harness. Also: signatures, approvals bound to the package, limits.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::path::{Path, PathBuf};

use pb_plugin::{PluginError, PluginHost, Signer, package};

/// A WASI command: stdin `r:<path>` prints the file at <path> in the first pre-opened folder; `w:<path>` writes
/// "hello" there. Any refused call exits with the WASI error number.
const FILE_TOOL: &str = r#"
(module
  (import "wasi_snapshot_preview1" "fd_read" (func $fd_read (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "path_open"
    (func $path_open (param i32 i32 i32 i32 i32 i64 i64 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "proc_exit" (func $proc_exit (param i32)))
  (memory (export "memory") 1)
  (data (i32.const 64) "hello")
  (func $check (param $e i32) (if (local.get $e) (then (call $proc_exit (local.get $e)))))
  (func (export "_start")
    (local $len i32) (local $fd i32) (local $n i32)
    ;; stdin -> 256..
    (i32.store (i32.const 0) (i32.const 256))
    (i32.store (i32.const 4) (i32.const 512))
    (call $check (call $fd_read (i32.const 0) (i32.const 0) (i32.const 1) (i32.const 16)))
    (local.set $len (i32.sub (i32.load (i32.const 16)) (i32.const 2)))
    (if (i32.eq (i32.load8_u (i32.const 256)) (i32.const 119)) ;; 'w'
      (then
        (call $check (call $path_open (i32.const 3) (i32.const 0) (i32.const 258) (local.get $len)
          (i32.const 9) (i64.const 64) (i64.const 0) (i32.const 0) (i32.const 32)))
        (i32.store (i32.const 0) (i32.const 64))
        (i32.store (i32.const 4) (i32.const 5))
        (call $check (call $fd_write (i32.load (i32.const 32)) (i32.const 0) (i32.const 1) (i32.const 16)))
        (return)))
    (call $check (call $path_open (i32.const 3) (i32.const 0) (i32.const 258) (local.get $len)
      (i32.const 0) (i64.const 2) (i64.const 0) (i32.const 0) (i32.const 32)))
    (i32.store (i32.const 0) (i32.const 1024))
    (i32.store (i32.const 4) (i32.const 4096))
    (call $check (call $fd_read (i32.load (i32.const 32)) (i32.const 0) (i32.const 1) (i32.const 16)))
    (i32.store (i32.const 4) (i32.load (i32.const 16)))
    (call $check (call $fd_write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 16)))))
"#;

fn write_package(dir: &Path, manifest: &str, files: &[(&str, &str)]) {
    std::fs::create_dir_all(dir).unwrap();
    std::fs::write(dir.join("plugin.toml"), manifest).unwrap();
    for (name, text) in files {
        std::fs::write(dir.join(name), text).unwrap();
    }
}

fn tool_manifest(permissions: &str) -> String {
    format!(
        "id = \"file-tool\"\nname = \"File tool\"\nversion = \"1.0.0\"\napi = 1\nkind = \"analysis\"\nruntime = \"wasm\"\n\
         entry = \"tool.wat\"\n[permissions]\ntime_s = 5\nmemory_mb = 16\n{permissions}\n"
    )
}

struct Setup {
    _tmp: tempfile::TempDir,
    host: PluginHost,
    project: PathBuf,
    outside: PathBuf,
    src: PathBuf,
}

fn setup(permissions: &str) -> Setup {
    let tmp = tempfile::tempdir().unwrap();
    let project = tmp.path().join("project");
    std::fs::create_dir_all(project.join("data")).unwrap();
    std::fs::write(project.join("data/inside.txt"), "declared data").unwrap();
    std::fs::write(project.join("private.txt"), "project secret").unwrap();
    let outside = tmp.path().join("outside.txt");
    std::fs::write(&outside, "secret outside the project").unwrap();
    let src = tmp.path().join("src");
    write_package(&src, &tool_manifest(permissions), &[("tool.wat", FILE_TOOL)]);
    package::sign(&src, None).unwrap();
    let host = PluginHost::new(tmp.path().join("plugins"));
    let pkg = host.install(&src).unwrap();
    assert_eq!(pkg.signer, Signer::Unsigned);
    host.approve("file-tool", &pkg.digest, true).unwrap();
    Setup {
        _tmp: tmp,
        host,
        project,
        outside,
        src,
    }
}

fn ask(s: &Setup, request: &str) -> (i32, String) {
    let out = s
        .host
        .run("file-tool", Some(&s.project), request.as_bytes(), &[])
        .unwrap();
    (out.exit_code, out.stdout)
}

#[test]
fn a_sandboxed_plugin_cannot_read_outside_its_declared_folder() {
    let s = setup(r#"read = ["data"]"#);
    assert_eq!(ask(&s, "r:inside.txt"), (0, "declared data".into()));
    for escape in [
        "r:../private.txt",
        "r:../../outside.txt",
        &format!("r:{}", s.outside.display()),
        "r:/etc/hosts",
    ] {
        let (code, out) = ask(&s, escape);
        assert_ne!(code, 0, "{escape} was not refused");
        assert!(!out.contains("secret"), "{escape} leaked {out}");
    }
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(&s.outside, s.project.join("data/link.txt")).unwrap();
        let (code, out) = ask(&s, "r:link.txt");
        assert_ne!(code, 0);
        assert!(!out.contains("secret"));
    }
    // read-only: writing in a folder declared for reading is refused
    let (code, _) = ask(&s, "w:new.txt");
    assert_ne!(code, 0);
    assert!(!s.project.join("data/new.txt").exists());
}

#[test]
fn undeclared_access_is_denied_and_declared_writes_stay_in_their_folder() {
    let none = setup("");
    let (code, out) = ask(&none, "r:data/inside.txt");
    assert_ne!(code, 0, "a plug-in without file permissions read a file");
    assert!(out.is_empty());

    let w = setup(r#"write = ["out"]"#);
    assert_eq!(ask(&w, "w:result.txt").0, 0);
    assert_eq!(
        std::fs::read_to_string(w.project.join("out/result.txt")).unwrap(),
        "hello"
    );
    assert_ne!(ask(&w, "w:../escaped.txt").0, 0);
    assert!(!w.project.join("escaped.txt").exists());
}

#[test]
fn approval_is_bound_to_the_package_and_its_permissions() {
    let s = setup(r#"read = ["data"]"#);
    // a changed file after installation withdraws the approval
    let installed = s.host.root().join("file-tool");
    std::fs::write(installed.join("tool.wat"), FILE_TOOL.replace("hello", "HELLO")).unwrap();
    assert!(matches!(
        s.host.run("file-tool", Some(&s.project), b"r:inside.txt", &[]),
        Err(PluginError::Package(_))
    ));
    // re-signing locally gives a new digest: still not approved until the user approves it again
    package::sign(&installed, None).unwrap();
    assert!(matches!(
        s.host.run("file-tool", Some(&s.project), b"r:inside.txt", &[]),
        Err(PluginError::NotApproved(_))
    ));
    // widening permissions also needs a new approval
    std::fs::write(installed.join("plugin.toml"), tool_manifest(r#"read = ["data", "."]"#)).unwrap();
    let digest = package::sign(&installed, None).unwrap();
    assert!(matches!(
        s.host.run("file-tool", Some(&s.project), b"r:inside.txt", &[]),
        Err(PluginError::NotApproved(_))
    ));
    assert!(s.host.approve("file-tool", "0".repeat(64).as_str(), true).is_err());
    assert!(
        s.host.approve("file-tool", &digest, false).is_err(),
        "unsigned packages need explicit consent"
    );
    s.host.approve("file-tool", &digest, true).unwrap();
    assert_eq!(ask(&s, "r:inside.txt").0, 0);
    // removing the plug-in removes its approval
    s.host.remove("file-tool").unwrap();
    assert!(s.host.approvals().unwrap().is_empty());
    assert!(s.src.exists());
}

#[test]
fn signatures_are_checked_against_trusted_keys() {
    let tmp = tempfile::tempdir().unwrap();
    let src = tmp.path().join("src");
    write_package(&src, &tool_manifest(""), &[("tool.wat", FILE_TOOL)]);
    let (pk, sk) = package::generate_keypair().unwrap();
    let key = package::secret_key(&sk).unwrap();
    let digest = package::sign(&src, Some(&key)).unwrap();
    let host = PluginHost::new(tmp.path().join("plugins"));

    // not trusted yet: refused at install
    assert!(matches!(host.inspect(&src).unwrap().signer, Signer::Untrusted(_)));
    assert!(matches!(host.install(&src), Err(PluginError::Signature(_))));
    let id = host.trust_key(&pk).unwrap();
    assert_eq!(host.trust_key(&pk).unwrap(), id);
    let pkg = host.install(&src).unwrap();
    assert_eq!(pkg.signer, Signer::Trusted(id));
    assert_eq!(pkg.digest, digest);
    host.approve("file-tool", &digest, false).unwrap();
    assert!(host.list().unwrap()[0].approved);

    // tampering is detected: a changed file, an added file, a forged listing
    std::fs::write(src.join("tool.wat"), FILE_TOOL.replace("hello", "HELLO")).unwrap();
    assert!(matches!(host.inspect(&src), Err(PluginError::Package(_))));
    let files = package::hash_files(&src).unwrap();
    std::fs::write(src.join("SHA256SUMS"), package::listing(&files)).unwrap();
    assert!(
        matches!(host.inspect(&src), Err(PluginError::Signature(_))),
        "a forged listing passed"
    );
    std::fs::write(host.root().join("file-tool/extra.py"), "print(1)").unwrap();
    let listed = host.list().unwrap();
    assert!(!listed[0].approved && listed[0].problem.is_some());
}

#[test]
fn limits_stop_runaway_plugins() {
    let tmp = tempfile::tempdir().unwrap();
    let host = PluginHost::new(tmp.path().join("plugins"));
    let manifest = |id: &str, entry: &str| {
        format!(
            "id = \"{id}\"\nname = \"x\"\nversion = \"1\"\napi = 1\nkind = \"model\"\nruntime = \"wasm\"\nentry = \"{entry}\"\n\
             [permissions]\ntime_s = 0.3\nmemory_mb = 2\n"
        )
    };
    let spin = "(module (func (export \"pb_predict\") (param f64 f64) (result f64) (loop $l (br $l)) (f64.const 0)))";
    let big = "(module (memory 100) (func (export \"pb_predict\") (param f64 f64) (result f64) (f64.const 0)))";
    for (id, wat) in [("spin", spin), ("big", big)] {
        let dir = tmp.path().join(id);
        write_package(&dir, &manifest(id, "m.wat"), &[("m.wat", wat)]);
        let digest = package::sign(&dir, None).unwrap();
        host.install(&dir).unwrap();
        host.approve(id, &digest, true).unwrap();
    }
    let start = std::time::Instant::now();
    let err = host.predict("spin", &[(300.0, 0.0)]).unwrap_err();
    assert!(matches!(err, PluginError::Limit(_)), "{err}");
    assert!(start.elapsed().as_secs_f64() < 5.0);
    let err = host.predict("big", &[(300.0, 0.0)]).unwrap_err();
    assert!(matches!(err, PluginError::Limit(_)), "{err}");
}

#[test]
fn template_plugin_passes_the_check_value_harness() {
    let template = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../plugins/templates/wasm-model");
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join("sutherland-air");
    std::fs::create_dir_all(&dir).unwrap();
    for name in ["plugin.toml", "sutherland.wat"] {
        std::fs::copy(template.join(name), dir.join(name)).unwrap();
    }
    let digest = package::sign(&dir, None).unwrap();
    let host = PluginHost::new(tmp.path().join("plugins"));
    let results = host.check(&dir).unwrap();
    assert_eq!(results.len(), 3);
    for r in &results {
        assert!(
            r.pass,
            "{} K: {} vs {} ({:+.3} %)",
            r.check.temperature,
            r.value,
            r.check.expected,
            100.0 * r.rel_dev
        );
    }
    // at T0 Sutherland's law returns eta0 exactly
    host.install(&dir).unwrap();
    host.approve("sutherland-air", &digest, true).unwrap();
    let v = host.predict("sutherland-air", &[(273.15, 0.0)]).unwrap();
    assert!((v[0] - 1.716e-5).abs() < 1e-18);
}
