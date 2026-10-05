# CLAUDE.md — instructions for Claude Code in the PropBench repository

## What this project is
A cross-platform desktop application for developing, validating and exporting thermophysical property models of
new fluids. Tauri/Rust shell (UI, scheduler, storage, environments, sandbox) + Python science worker that calls
existing libraries (CoolProp, FeOs, SciPy, lmfit, statsmodels, ...). Read README.md §0, §2, §4, §6, §7 first.
Layout: `crates/pb-*` (Rust shell), `worker/` (Python package `propbench`, uv project), `app/` (Tauri + Svelte).

## Golden rules
0. **Integrate, don't rebuild.** Before writing any non-trivial algorithm, check the integration map (README §0) and
   look for a maintained open-source library or tool with a compatible licence. Write glue, not re-implementations.
   GPL/AGPL tools only as separate processes; never copy their code. Ask before adding any dependency.
1. **Scientific correctness first.** Never change a model equation without a test reproducing a published check value.
   Never weaken, delete or loosen tolerances of a check-value or regression test to make code pass.
2. **Layering.** `crates/pb-*` never depend on `app/`. Every GUI action is a Tauri command that calls a `pb-engine`
   function also reachable from `pb-cli` and from the `propbench` Python package. Science lives only in `worker/`.
3. **Safety.** No `unsafe` code (`unsafe_code = "forbid"` for the workspace).
   No `unwrap()`/`expect()` in library code: return `Result` with `thiserror` error types.
4. **Licences.** MIT project. Do not copy code from GPL projects (pychemqt, DWSIM). Implement models from original
   papers/NIST reports and cite them in doc comments. New dependencies must be MIT/Apache/BSD; ask first.
5. **Tests with every change**, in the same commit. Before finishing a task run the full check below. No network in tests.
6. **Reproducibility.** All randomness takes an explicit seed (Python: `numpy.random.Generator(PCG64(seed))`;
   Rust, if ever needed: `rand_chacha`); results identical on all OS.
7. **Performance.** Parallelise across worker processes only in fitting/validation loops; batch property calls inside
   the worker instead of one RPC per state; keep benchmarks green (README §7 budgets). Measure before optimising.

## Backend rules
- All property calls go through the single `Backend` interface; never call a library directly from workflow code.
- Every backend adapter has cross-check tests against at least one other backend at published states (until a second
  backend exists, CoolProp is tested against published check values only).
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
- The UI never computes: all work goes through `pb-engine`, which runs it in a supervised Python worker
  (JSON-RPC 2.0 over stdio). Every job is deterministic given its key and seed.
- The worker runs in the bundled core environment with `python -I`; it never reads the user's site-packages or PATH.
- Project writes are atomic (temp file + rename) and versioned with a migration for every schema change.
- Never store credentials or tokens in project files or logs; use the OS keychain.

## Commands
- Worker environment: `uv sync --project worker` (uv-managed Python only; never the system Python)
- Full check: `cargo fmt --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
  && uv run --project worker ruff check worker && uv run --project worker ruff format --check worker
  && uv run --project worker pytest && (cd app && npm run check && npm test)`
- Regression case only: `uv run --project worker pytest -k cf3i`
- CLI: `cargo run -p pb-cli -- --help`
- App: `cd app && npm run tauri dev` · UI checks: `npm run check && npm test`
- Pre-commit hooks: `uv run --project worker pre-commit install`

## Conventions
- Units: SI internally (K, Pa, Pa·s, mol/m³); `pint` at the worker's public boundaries; convert only at import/display.
- Deviations: ARD = 100·(exp − model)/model; positive means model below data. Same sign everywhere.
- `Model` protocol (`propbench.models`): `fit`, `predict`, `params`, `bounds`, `check_values`, `validity`, `reference`.
- Serialization with `serde`; project files are SQLite + JSON; any format change needs a migration and a test.
- Exported figures: one plot per figure, legends inside axes, journal presets, vector + PNG up to 2500 dpi.

## Reference regression case (must always pass)
`worker/tests/regression/test_cf3i.py` reproduces the CF₃I viscosity paper (expected values in README §7); data in
`worker/tests/data/cf3i/` (from M1).

## Ask before
Adding a dependency, changing the project file format or a public API, touching the worker RPC protocol or process supervision, or altering any expected
value in a regression test.
