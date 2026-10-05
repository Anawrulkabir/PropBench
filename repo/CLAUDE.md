# CLAUDE.md — instructions for Claude Code in the PropBench repository

## What this project is
A cross-platform desktop application for developing, validating and exporting thermophysical property models of
new fluids. Tauri/Rust shell (UI, scheduler, storage, environments, sandbox) + Python science worker that calls
existing libraries (CoolProp, FeOs, SciPy, lmfit, statsmodels, ...). Read README.md §2, §4, §6, §7 first.

## Golden rules
0. **Integrate, don't rebuild.** Before writing any non-trivial algorithm, check the integration map (README §0) and
   look for a maintained open-source library or tool with a compatible licence. Write glue, not re-implementations.
   GPL/AGPL tools only as separate processes; never copy their code. Ask before adding any dependency.
1. **Scientific correctness first.** Never change a model equation without a test reproducing a published check value.
   Never weaken, delete or loosen tolerances of a check-value or regression test to make code pass.
2. **Layering.** `crates/pb-*` never depend on `app/`. Every GUI action is a Tauri command that calls a core function
   also exposed in `pb-cli` and `pb-py`.
3. **Safety.** No `unsafe` outside `pb-thermo/src/coolprop_ffi.rs`; every `unsafe` block has a `// SAFETY:` comment.
   No `unwrap()`/`expect()` in library code: return `Result` with `thiserror` error types.
4. **Licences.** MIT project. Do not copy code from GPL projects (pychemqt, DWSIM). Implement models from original
   papers/NIST reports and cite them in doc comments. New dependencies must be MIT/Apache/BSD; ask first.
5. **Tests with every change**, in the same commit. Before finishing a task run the full check below. No network in tests.
6. **Reproducibility.** All randomness takes an explicit seed (`rand_chacha`); results identical on all OS.
7. **Performance.** Parallelise with `rayon` only in fitting/validation loops; keep criterion benchmarks green
   (README §7 budgets). Measure before optimising.

## Backend rules
- All property calls go through the single `Backend` interface; never call a library directly from workflow code.
- Every backend adapter has cross-check tests against at least one other backend at published states.
- Licensed software (REFPROP, TREND) is never bundled or redistributed; connect only to the user's installed copy.

## Distribution rules (effortless on every OS)
- Never require users to install Python, Rust, Node, compilers or admin rights; bundle what the app needs.
- Every feature must work on Windows, macOS and Linux (x64 and ARM64); OS-specific code goes behind one interface with tests on all three.
- No feature may break the clean-VM release gate (README §4e).

## Core principle: isolation
- Never install, modify or write anything outside the app data folder and the user's project folder.
- Never require admin rights or modify system PATH, system Python or global package caches.
- User scripts and plug-ins always run in the project environment, in a separate process with time/memory limits.

## AI and integrations rules
- AI output never executes code or changes data without an explicit, previewed user confirmation.
- AI-generated CAD or simulation setups go through validated engine tools; never write unchecked solver input files.
- Store prompt, provider, model and version with every AI-generated artefact.
- Remote execution only over SSH with the user's keys; never open listening ports by default.

## Plug-in rules
- Third-party plug-ins run sandboxed (WASM) or in the project environment (Python); never in the core process unsandboxed.
- Every plug-in declares permissions in plugin.toml; enforce them; deny anything undeclared.
- Implement add-ons from published methods and open data only; never copy proprietary code, data or databases.

## Engine and storage rules
- The UI never computes: all work goes through `pb-engine` jobs. Every job is deterministic given its key and seed.
- Project writes are atomic (temp file + rename) and versioned with a migration for every schema change.
- Never store credentials or tokens in project files or logs; use the OS keychain.

## Commands
- Full check: `cargo fmt --check && cargo clippy --workspace --all-targets -- -D warnings && cargo nextest run --workspace`
- Regression case only: `cargo nextest run -p pb-validate cf3i`
- Benchmarks: `cargo bench -p pb-models`
- CLI: `cargo run -p pb-cli -- --help`
- App: `cd app && npm run tauri dev` · UI checks: `npm run check && npm test`
- Python bindings: `maturin develop -m crates/pb-py/Cargo.toml && pytest crates/pb-py/tests`
- Docs: `mdbook serve docs`

## Conventions
- Units: SI internally (K, Pa, Pa·s, mol/m³); typed with `uom` at public boundaries; convert only at import/display.
- Deviations: ARD = 100·(exp − model)/model; positive means model below data. Same sign everywhere.
- `Model` trait (pb-models): `fit`, `predict`, `params`, `bounds`, `check_values`, `validity`, `reference`.
- Serialization with `serde`; project files are SQLite + JSON; any format change needs a migration and a test.
- Exported figures: one plot per figure, legends inside axes, journal presets, vector + PNG up to 2500 dpi.

## Reference regression case (must always pass)
`tests/regression/cf3i.rs` reproduces the CF₃I viscosity paper (expected values in README §7); data in `tests/data/cf3i/`.

## Ask before
Adding a dependency, changing the project file format or a public API, touching FFI code, or altering any expected
value in a regression test.
