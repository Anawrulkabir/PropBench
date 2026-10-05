// Builds the self-contained Python that ships inside the installer (README §4e): a relocatable standalone CPython
// (python-build-standalone, installed by uv) with the worker's locked runtime dependencies and the propbench package.
//
// Output: app/src-tauri/resources/python/  (bundled by tauri.bundle.conf.json as <resources>/python)
// Isolation: uv installs into target/python-bundle/ inside the repository; --no-bin and --no-registry keep it from
// adding executables to ~/.local/bin or entries to the Windows registry.
//
// Usage: node scripts/bundle-python.mjs   (needs uv on PATH; runs on Windows, macOS and Linux)

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const appDir = path.resolve(import.meta.dirname, "..");
const repoDir = path.resolve(appDir, "..");
const workerDir = path.join(repoDir, "worker");
const workDir = path.join(repoDir, "target", "python-bundle");
const outDir = path.join(appDir, "src-tauri", "resources", "python");
const isWindows = process.platform === "win32";

function run(cmd, args, options = {}) {
  console.log(`> ${cmd} ${args.join(" ")}`);
  return execFileSync(cmd, args, { stdio: ["ignore", "pipe", "inherit"], encoding: "utf8", ...options });
}

function pythonIn(dir) {
  return isWindows ? path.join(dir, "python.exe") : path.join(dir, "bin", "python3");
}

// 1. Standalone CPython at the version the worker is developed and tested with.
const pythonVersion = fs.readFileSync(path.join(workerDir, ".python-version"), "utf8").trim();
const installDir = path.join(workDir, "install");
fs.rmSync(workDir, { recursive: true, force: true });
fs.mkdirSync(workDir, { recursive: true });
run("uv", ["python", "install", pythonVersion, "--install-dir", installDir, "--no-bin", "--no-registry"]);
const installed = fs.readdirSync(installDir).filter((name) => name.startsWith("cpython-"));
if (installed.length !== 1) throw new Error(`expected one CPython in ${installDir}, found: ${installed.join(", ")}`);

fs.rmSync(outDir, { recursive: true, force: true });
// tauri-build stages resources in target/<profile>/python without deleting stale files: start those clean too.
for (const profile of ["debug", "release"]) {
  fs.rmSync(path.join(repoDir, "target", profile, "python"), { recursive: true, force: true });
}
fs.cpSync(path.join(installDir, installed[0]), outDir, { recursive: true, verbatimSymlinks: true });

// 2. Make the tree free of symlinks (installers copy them as duplicate files): keep one real `bin/python3`.
if (!isWindows) {
  const bin = path.join(outDir, "bin");
  const real = fs.realpathSync(path.join(bin, "python3"));
  fs.rmSync(path.join(bin, "python3"));
  fs.copyFileSync(real, path.join(bin, "python3"));
  fs.chmodSync(path.join(bin, "python3"), 0o755);
  for (const name of fs.readdirSync(bin)) {
    if (name !== "python3") fs.rmSync(path.join(bin, name), { recursive: true, force: true });
  }
  removeSymlinks(outDir);
}

// 3. Runtime dependencies exactly as locked in worker/uv.lock (hash-checked), then the propbench package itself.
const python = pythonIn(outDir);
const requirements = path.join(workDir, "requirements.txt");
run("uv", [
  "export", "--project", workerDir, "--frozen", "--no-dev", "--no-emit-project",
  "--format", "requirements-txt", "--output-file", requirements,
]);
const pipArgs = ["pip", "install", "--python", python, "--break-system-packages", "--no-config"];
run("uv", [...pipArgs, "--require-hashes", "-r", requirements]);
run("uv", [...pipArgs, "--no-deps", workerDir]);
// pip is not needed at run time; project environments (M1c) are managed by uv.
run("uv", ["pip", "uninstall", "--python", python, "--break-system-packages", "--no-config", "pip"]);

// 4. Remove what the worker never uses: GUI toolkit (Tcl/Tk), test suite, IDLE, headers, man pages, terminfo.
const stdlib = run(python, ["-I", "-c", "import sysconfig; print(sysconfig.get_paths()['stdlib'])"]).trim();
for (const name of ["test", "idlelib", "tkinter", "turtledemo", "ensurepip"]) {
  fs.rmSync(path.join(stdlib, name), { recursive: true, force: true });
}
const dynload = isWindows ? path.join(outDir, "DLLs") : path.join(stdlib, "lib-dynload");
for (const name of fs.existsSync(dynload) ? fs.readdirSync(dynload) : []) {
  // The Tk extension links the Tcl/Tk libraries removed below (and makes AppImage's linuxdeploy fail).
  if (/^_tkinter\.|^(tcl|tk)\d.*\.dll$/.test(name)) fs.rmSync(path.join(dynload, name));
}
for (const name of ["tcl", "include", "share"]) {
  fs.rmSync(path.join(outDir, name), { recursive: true, force: true });
}
const libDir = path.join(outDir, "lib");
if (fs.existsSync(libDir)) {
  for (const name of fs.readdirSync(libDir)) {
    // On Linux bin/python3 links libpython statically; the shared copy only serves embedding.
    const unused = /^(tcl|tk|itcl|thread)\d|^lib(tcl|tk)\d|^pkgconfig$/.test(name) ||
      (process.platform === "linux" && /^libpython3/.test(name));
    if (unused) fs.rmSync(path.join(libDir, name), { recursive: true, force: true });
  }
}

// 5. Precompile site-packages (the worker runs with -B and never writes bytecode at run time).
const sitePackages = run(python, ["-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"]).trim();
run(python, ["-I", "-W", "ignore", "-m", "compileall", "-q", "-j", "0", sitePackages]);

// 6. Smoke test: the bundled interpreter imports the worker in isolated mode.
const versions = run(python, [
  "-I", "-B", "-c",
  "import sys, CoolProp, propbench; print(sys.version.split()[0], CoolProp.__version__, propbench.__version__)",
]).trim();
console.log(`bundled Python ready in ${outDir}: python, CoolProp, propbench = ${versions}`);

function removeSymlinks(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isSymbolicLink()) {
      const target = fs.realpathSync(full);
      fs.rmSync(full);
      // Shared-library aliases (libpython3.12.so -> libpython3.12.so.1.0) are only needed for linking: drop them.
      // Anything else is replaced by a copy of its target.
      if (!/\.(so|dylib)$/.test(entry.name)) fs.cpSync(target, full, { recursive: true });
    } else if (entry.isDirectory()) {
      removeSymlinks(full);
    }
  }
}
