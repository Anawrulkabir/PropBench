# PropBench plug-ins (SDK)

A plug-in adds a model, backend, importer/exporter, analysis tool, plot type, report template, data source or AI tool
(README §2f). A new model is **one file + tests + a manifest**.

| Template | Runs as | Use for |
|---|---|---|
| [`templates/wasm-model`](templates/wasm-model) | WebAssembly in wasmtime: sandboxed, sees nothing undeclared | third-party plug-ins (recommended) |
| [`templates/python-model`](templates/python-model) | Python in the project environment, separate process, guarded | your own models; full `propbench` API |

## Manifest (`plugin.toml`)

```toml
id = "my-model"            # lower-case letters, digits, - and _
name = "My viscosity model"
version = "1.0.0"
api = 1                    # plug-in API this plug-in needs
kind = "model"             # model, backend, importer, exporter, analysis, plot-type, report-template, data-source, ai-tool
runtime = "wasm"           # or "python"
entry = "model.wat"        # .wasm/.wat (WASM) or .py (Python)
reference = "Author, Journal 1 (2026) 1"   # the publication the method comes from

[permissions]              # nothing is granted that is not declared
network = false            # Python only; WASM plug-ins never get network in API 1
gpu = false
read = ["data"]            # project folders the plug-in may read
write = ["out"]            # project folders the plug-in may read and write
time_s = 60                # per run
memory_mb = 512

[[check]]                  # published values the plug-in must reproduce ("verified" mark)
temperature = 300.0        # K
molar_density = 0.0        # mol/m³
expected = 1.846e-5        # SI
rel_tol = 0.01
source = "Incropera et al. (2007), Table A.4"
```

Folders are relative to the user's project folder; absolute paths and `..` are refused. The user sees these
permissions in words when installing and approves them; the approval is bound to the package digest, so any change to
the package (or its permissions) needs a new approval.

## Plug-in API 1

- **WASM model**: export `pb_predict(temperature_K: f64, molar_density: f64) -> f64` (SI units). No imports are needed.
- **WASM tool**: a WASI preview 1 command (`_start`) reading its request on stdin and writing its answer to stdout. Each
  declared folder is pre-opened under its own name (`read` read-only, `write` read-write). Nothing else exists for it: no
  other folder, no environment variables, no network, no clock beyond WASI's.
- **Python model**: the entry module defines `MODEL` (or `create()`), an object with the `propbench.models.Model`
  protocol (`predict`, `params`, `with_params`, `bounds`, `check_values`, `validity`, `reference`).
- **Python tool**: the entry module defines `run(params, context)` returning JSON; `context` has `project_dir`, `read`
  and `write` (absolute folders).

Python plug-ins run with an audit-hook guard: file access outside the declared folders (and the Python installation),
undeclared network access, starting processes and loading native libraries raise `PermissionError`. The guard
enforces what a well-behaved plug-in declared; it is not a sandbox against hostile code, so third-party plug-ins
should be WASM.

## Develop, check, sign

```sh
# check-value harness
propbench plugin check plugins/templates/wasm-model            # WASM
uv run --project worker pytest plugins/templates/python-model  # Python (uses propbench.plugins.check)

# sign (minisign keys; keep the .key private, share the .pub)
propbench plugin keygen me
propbench plugin sign my-plugin --key me.key                    # writes SHA256SUMS and plugin.minisig

# install and run as a user would
propbench --plugins-dir /tmp/pb-plugins plugin trust me.pub
propbench --plugins-dir /tmp/pb-plugins plugin install my-plugin            # prints the digest and permissions
propbench --plugins-dir /tmp/pb-plugins plugin approve my-id --digest <digest>
propbench --plugins-dir /tmp/pb-plugins plugin predict my-id --state 300,0
propbench --plugins-dir /tmp/pb-plugins plugin python my-py-id --method check
```

`SHA256SUMS` lists the SHA-256 of every file (`__pycache__` and `.pytest_cache` excluded; Python plug-ins never use
cached bytecode). Verification recomputes it and requires an exact match, so added, removed or changed files are
detected, then checks the minisign signature against the user's trusted keys. Unsigned packages can be installed for
local development only, with an explicit confirmation.

## Registry

Plug-ins are distributed like components (README §2b): a registry entry of kind `plugin` names a zip archive (with
size and SHA-256) holding `component.json` and the signed package in `plugin/`. After the components manager installs
it, the plug-in manager verifies the signature and asks the user to approve its permissions. Implement add-ons from
published methods and open data only; never copy proprietary code, data or databases.
