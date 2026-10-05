# Contributing to PropBench

Thank you for helping. PropBench is in pre-alpha (milestone M0); this guide will grow with the project.
Read `README.md` (§0 integrate, don't rebuild; §4 architecture) and `CLAUDE.md` (the project rules) first.

## Layout

| Path | What | Language |
|---|---|---|
| `worker/` | `propbench` package: backends, models, the worker process (JSON-RPC over stdio) | Python (uv) |
| `crates/pb-engine` | starts and supervises the worker | Rust |
| `crates/pb-cli` | `propbench` command line | Rust |
| `app/` | Tauri desktop app: `src/` (Svelte + TypeScript UI), `src-tauri/` (Rust commands) | TS / Rust |
| `docs/` | user documentation | Markdown |
| `design/` | screen mockups | HTML |

## Set up

You need Rust (rustup; the toolchain is pinned in `rust-toolchain.toml`), Node.js 20+ and
[uv](https://docs.astral.sh/uv/). No system Python is needed: uv downloads a managed one. On Linux, also install the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/) (WebKitGTK 4.1 and friends).

```bash
uv sync --project worker                      # worker/.venv with CoolProp and the dev tools
cd app && npm ci && cd ..                     # UI dependencies
uv run --project worker pre-commit install    # format and lint checks on every commit
```

## Run

```bash
cargo run -p pb-cli -- property --fluid R134a --pair PT_INPUTS --values 1e6,300 --output Dmass
cd app && npm run tauri dev                   # desktop app in development mode
```

In development the engine uses `worker/.venv`. Set `PB_WORKER_PYTHON` to use another interpreter.

## Check before every commit

```bash
cargo fmt --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace \
  && uv run --project worker ruff check worker && uv run --project worker ruff format --check worker \
  && uv run --project worker pytest worker && (cd app && npm run check && npm test)
```

## Build the installers (unsigned)

```bash
cd app && npm run tauri build -- --config src-tauri/tauri.bundle.conf.json
```

This first runs `scripts/bundle-python.mjs`, which puts a standalone Python with the locked worker dependencies in
`app/src-tauri/resources/python/`. Installers land in `target/release/bundle/`. If you rebuild after changing the
bundle, delete `target/release/bundle/` first: Tauri does not remove stale files from its staging folders.

To check that the installers work, run `scripts/ci/test-installers.sh` from the repository root. It unpacks or
installs them under `target/installed/` and runs the end-to-end tests against the Python inside (CI does this on
every OS).

## Rules (summary of README §8 and CLAUDE.md)

- **Open an issue before a large change.**
- **Ask before adding a dependency.** Direct dependencies must be MIT, Apache-2.0 or BSD. GPL/AGPL tools only as
  separate processes; never copy their code.
- **Tests with every change**, in the same commit. Tests never use the network.
- **Scientific correctness first.** Every model ships with a reference, at least one published check value as a test,
  and a documented validity range. Never loosen a check-value tolerance to make code pass.
- **SI units internally**; convert only at import and display.
- **Isolation.** Nothing is written outside the app data folder and the user's project folder; no admin rights.
- **No `unsafe` Rust**, no `unwrap()`/`expect()` outside tests.
