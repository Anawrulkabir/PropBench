# PropBench — an open desktop workbench for thermophysical property models of new fluids

*Working name. Status: design document for version 0.1 (pre-alpha). Tauri/Rust shell + Python science worker; built by integrating open-source tools (§0).*

PropBench takes a laboratory from **new measurements** to a **validated, documented, exportable property model**,
on Windows, macOS and Linux, without writing code.

## 0. Principle: integrate, don't rebuild

PropBench assembles mature open-source tools into one handy research workbench. We write **glue, workflow and user
experience**; we do not re-implement solvers, fitting libraries, plotting engines or CAD kernels. A feature is built
from scratch only when no maintained open tool with a compatible licence exists (currently: the validation and
consistency workflow, and the data-evaluation add-on).

**Architecture consequence.** Rust (Tauri) is used only for the shell: windows, scheduler, storage, environments,
plug-in sandbox and process management. Science runs in a **Python worker** inside the managed project environment,
calling existing libraries whose compiled cores (CoolProp C++, FeOs Rust, NumPy/SciPy C/Fortran) deliver the
performance. Large tools (OpenFOAM, Gmsh, CalculiX, rclone, Pandoc) run as separate processes.

**Licence rules.** MIT/BSD/Apache: may be embedded. LGPL: dynamic linking or separate process. GPL/AGPL: separate
process only, never linked or copied. Unknown licence: do not use until verified.

### Integration map

| Feature | Tool(s) we integrate | Licence | How |
|---|---|---|---|
| Desktop shell | Tauri | MIT/Apache | host |
| Docking panels, data grid | dockview; TanStack Table | MIT | UI library |
| Node canvas (setup builder) | Svelte Flow | MIT | UI library |
| 2D interactive plots | Plotly.js or Apache ECharts | MIT / Apache | UI library |
| Publication figure export | matplotlib | PSF/BSD | worker |
| 3D views, CFD fields | three.js; vtk.js; PyVista | MIT / BSD / MIT | UI + worker |
| Code editor, terminal | Monaco; xterm.js + portable-pty | MIT | UI library |
| Python console | Jupyter kernel (ipykernel, jupyter_client) | BSD | worker process |
| Equations of state, transport | CoolProp; FeOs; teqp; thermo (see §2i) | MIT (/Apache) | worker |
| Licensed backends (user's copy) | REFPROP via ctREFPROP; TREND | user licence; never bundled | optional connector |
| REFPROP (user's licence) | ctREFPROP | MIT wrapper | worker, optional |
| Units, uncertainties | pint; uncertainties | BSD | worker |
| Fitting, global fits, bounds | SciPy; lmfit | BSD | worker |
| Statistics, diagnostics | statsmodels | BSD | worker |
| Bayesian analysis | PyMC or NumPyro | Apache | worker |
| Symbolic maths, derivatives | SymPy | BSD | worker |
| Automatic equation search | PySR | Apache | add-on |
| Measurement planning | BoTorch / Ax | MIT | add-on |
| ML models | PyTorch; ONNX Runtime | BSD / MIT | worker |
| Tables, fast queries | Polars or pandas; DuckDB | MIT / BSD / MIT | worker |
| References | Crossref API (habanero); Zotero API; citeproc-py | MIT / BSD | worker |
| Reports | python-docx; Typst; Pandoc | MIT / Apache / GPL | worker; Pandoc as process |
| Environments | uv | MIT/Apache | process |
| Git and GitHub | gitoxide; octocrab | MIT/Apache | shell |
| Cloud storage | rclone (Drive, OneDrive, Dropbox, S3, ...) | MIT | process |
| Remote execution | OpenSSH (system) | BSD | process |
| Plug-in sandbox | wasmtime | Apache | shell |
| AI providers | LiteLLM; MCP SDK | MIT | worker / shell |
| Molecules | RDKit; 3Dmol.js | BSD | worker + UI |
| Pipe and fitting pressure drop (1D) | fluids (ChEDL) | MIT | worker |
| CAD scripting and import | CadQuery or build123d; OpenCascade | Apache; LGPL | worker |
| Meshing | Gmsh | GPL | process |
| CFD | OpenFOAM | GPL | process |
| Structural / thermal FEA | CalculiX; Elmer | GPL | process |
| Plot digitizer | WebPlotDigitizer | AGPL | separate process only; or a permissive alternative after licence check |
| ML viscosity models | DeepESNet | verify | do not bundle until verified |
| AI CFD automation | Foam-Agent | verify | ideas only until verified |

**What we build:** project/session model, import mapping, data checks, consistency analysis, the validation and
model-selection protocol, uncertainty workflow, report assembly, component/plug-in registry, and the data-evaluation
add-on.

## 1. Why this software

Three problems met while modelling the viscosity of CF₃I (R13I1), all general:

1. **Free libraries lack models for new fluids.** CoolProp has no CF₃I viscosity model; REFPROP is paid; the
   open re-implementation of REFPROP's model (pychemqt) needed seven workarounds to run.
2. **No tool takes measurements to a validated model.** Every lab writes one-off scripts. Published models are
   therefore usually reported in-sample only, without tests on unseen states, physics checks or uncertainty.
3. **Nobody routinely checks new data against old data.** Two CF₃I datasets disagreeing by 5–9 % went unnoticed
   for 25 years and entered REFPROP.

Existing open-source projects are excellent **libraries** (CoolProp, FeOs, teqp, Clapeyron.jl, thermo) or
**process simulators** (DWSIM, pychemqt). None is a desktop application for the *model-development workflow*:
import → check → fit → validate → compare → report → export.

## 2. What the user can do (feature set)

| Area | Features |
|---|---|
| **Project** | One project file per fluid: datasets, models, studies, results; full history; undo; autosave |
| **Data** | Import Excel/CSV/ThermoML XML, manual entry; units and uncertainty handling; phase assignment from an EoS; duplicate and outlier detection; provenance (DOI, method, purity) |
| **Data consistency** | Overlap finder between datasets; model-free checks (e.g. pressure trend at equal T); dataset offsets with uncertainty; z-scores against stated uncertainties |
| **Thermodynamic backends** | CoolProp (default), FeOs PC-SAFT, cubic EoS, REFPROP if the user has a licence (via ctREFPROP); plug-in interface for others |
| **Model library** | Dilute gas (Chung, Neufeld collision integrals, polynomials); ECS with any reference fluid; residual entropy scaling (3-term, 4-term, group curves, Klenk-type); ML models (Gaussian process, fine-tuning of pretrained networks) as optional plug-ins |
| **Fitting** | Weighted least squares in relative deviation; bounds; multi-start; per-dataset scale factors; exact Bayesian fit for linear models; MCMC optional |
| **Validation** | Leave-one-state-out, leave-one-temperature-out, k-fold; configurable physics checks (monotonicity, dilute-gas limit, extrapolation range); bootstrap bands; EoS sensitivity; **selection rule locked before fitting** with an audit trail |
| **Comparison** | Literature and reference models (e.g. NIST NISTIR 8209 models with their check values) side by side with fitted ones |
| **Plots** | Deviation plots, isobars/isotherms with uncertainty bands, parity, p–T state map; journal styles; vector PDF and PNG up to 2500 dpi |
| **Reports** | One-click report (Word/PDF/Markdown): data summary, consistency, model tables, check values, figures; reproducibility bundle (inputs, versions, seeds) |
| **Export** | CoolProp fluid/transport JSON, Python/C function, Excel tables of recommended values |
| **Extensibility** | Plug-ins via Python entry points: a new model, backend, check or exporter is one file plus tests; embedded Python console; command-line batch mode for every GUI action |

Out of scope for 1.0: mixtures (planned for 2.0), process/cycle simulation, equation-of-state development.

## 2a. User workflows

A **New Project Wizard** opens at start and asks what the user wants to do; it then selects fluids and data sources
and installs only the components that task needs.

| Workflow | What the user does | Main output |
|---|---|---|
| Look up properties | Pure fluid or mixture; T, p (or other inputs); tables, plots, single points | Property tables, phase diagrams |
| Explore experimental data | Browse published measurements by fluid and property; compare with models | Deviation plots, data tables |
| Check data consistency | Find overlaps between datasets; model-free and model-based checks | Offsets with uncertainty, warnings |
| Fit a model | Own or published data; ECS, entropy scaling, PC-SAFT | Fitted parameters with uncertainty |
| Validate and compare | Unseen-state tests, physics checks, bootstrap, reference models | Validation report |
| Mixtures | Predict mixture properties; fit binary interaction parameters | Mixture model |
| Report and export | Report, publication figures, CoolProp export | Documents, model files |

## 2b. Small install, components on demand

The installer ships only the core (calculator, plots, projects, fitting and validation tools) and the CoolProp
fluid library. Everything else is a **component** installed from inside the app (Tools › Components) or
automatically by the wizard when a task needs it.

| Category | Components | Source / licence |
|---|---|---|
| Thermodynamic engines | FeOs (PC-SAFT, entropy-scaling transport), cubic equations | MIT / Apache-2.0 |
| Fluid parameter sets | PC-SAFT parameters (about 1800 substances); entropy-scaling viscosity parameters (952 substances, Klenk et al. 2026) | Published datasets; check each licence before bundling |
| Experimental data | NIST TRC ThermoML archive, one component per property (viscosity, density, thermal conductivity, phase equilibria) | Public archive |
| Reference transport models | NIST published models (NISTIR 8209) with their check values | Own implementation from the reports |
| Mixtures | Mixing rules, binary-parameter fitting | PropBench |
| Machine learning | Pretrained property networks (ONNX) | Per model |
| Connectors | REFPROP connector (uses the user's own licence; REFPROP is never redistributed) | — |
| Report templates | Elsevier, ACS, plain | PropBench |

**Mechanism.** A registry index (`registry.json`: id, version, size, SHA-256, dependencies, licence, URL) is hosted
on GitHub Releases. The app downloads the index, resolves dependencies, downloads each archive, verifies the
checksum, and unpacks it into the user's data folder. Components update independently of the app, can be removed,
and can be installed offline from a file. Data components are stored as compressed Parquet/SQLite for fast queries.

## 2c. Walkthrough of one study

| Step | Screen | What happens |
|---|---|---|
| 1 | Import | File (Excel, CSV, ThermoML XML) → map each column to a quantity and unit → fluid identified (name, CAS) → source recorded (DOI, method); mappings saved as templates |
| 2 | Data check | SI conversion; phase from file compared with the equation of state; duplicates, out-of-range and near-critical points; overlaps between datasets flagged; p–T state map |
| 3 | Study setup and run | Models to fit; validation scheme (leave-one-state-out, leave-one-temperature-out, k-fold, bootstrap, seed); physics checks; selection rule **locked before fitting**; parallel run queue with pause and stop |
| 4 | Results | Ranked candidates, rejected models and the reason, selected model with parameters and uncertainty band |
| 5 | Graph studio | Publication figures from any result or worksheet (below); export and report |

## 2d. Graph studio (Origin-style)

- **Plot types:** scatter, line, line + symbol, spline, step, error bars, confidence bands, column, box, histogram,
  contour, heat map, 3D surface, ternary (mixtures), polar, parity, deviation, residual Q–Q, and thermodynamic
  diagrams (p–T, p–h, T–s, p–ρ) with saturation curve and critical point.
- **Structure:** graph → layers (multiple axes, insets, linked axes) → plots; an object manager tree to select,
  hide, reorder and group plots.
- **Formatting:** axis scale (linear, log10, reciprocal 1/T, probability), range, major/minor ticks, rich-text titles
  with sub/superscripts and Greek letters; symbol shape, size, fill (solid, open, mapped to a column); line style,
  width, connection (straight, spline, step); colour by group or colour map; legends, text, arrows, reference bands.
- **Data:** plots stay linked to worksheets and study results, so figures update when a study is re-run.
- **Templates and export:** graph templates and themes; journal presets (Elsevier 90/190 mm, ACS 85 mm); PDF, SVG,
  EPS (vector) and PNG, TIFF up to 2500 dpi; one figure per file; batch export of all figures in a project.

## 2e. Core research tools

| # | Feature | What it gives the researcher | Release |
|---|---|---|---|
| 1 | **Worksheets** | Origin-style tables: units row, formula columns (e.g. η = ν·ρ, ρ from the EoS), masking (excluded from fits but kept and shown), sort, filter, column statistics | Beta |
| 2 | **Plot digitizer** | Extract data points from figures in PDFs/images when only a plot is published; calibrated axes, log scales, error bars | 0.2 |
| 3 | **ThermoML export** | Write new measurements in ThermoML for journal submission (e.g. J. Chem. Eng. Data) | 0.2 |
| 4 | **General curve fitting** | Any user equation (editor, automatic derivatives), bounds, fixed parameters, weights, **global fits with shared parameters** and per-dataset scale factors, multi-start | Beta |
| 5 | **Model comparison and diagnostics** | AIC/BIC, F-test for nested models, residual plots, parameter correlation matrix, outlier tests | Beta |
| 6 | **Uncertainty propagation (GUM)** | Uncertainty budgets per input, linear and Monte Carlo propagation, coverage factors | Beta |
| 7 | **Property calculator and tables** | Property at a state, saturation tables, isotherm/isobar tables, thermodynamic diagrams | 0.2 |
| 8 | **Sensitivity analysis and sweeps** | Systematic variation of inputs (EoS, weights, data subsets); variance-based sensitivity | 0.3 |
| 9 | **Measurement planning** | Rank candidate (T, p) states by expected reduction of model uncertainty | 0.3 |
| 10 | **References** | DOI lookup, BibTeX/Zotero import, citations attached to datasets and models, bibliography in reports | Beta |
| 11 | **Lab notebook** | Timestamped notes linked to datasets, models and figures, versioned with the project | 0.2 |
| 12 | **Table export** | Results as LaTeX/Word tables in journal style; supplementary data files | 0.3 |

## 2f. Plug-ins and add-ons

**Plug-in types:** models · thermodynamic backends · importers/exporters · analysis tools · plot types · report
templates · data sources · AI tools.

**Languages:** Python (runs in the project environment; easiest for researchers) · WebAssembly via `wasmtime`
(portable and sandboxed; recommended for third-party plug-ins) · Rust (fastest; for reviewed plug-ins).

**Manifest (`plugin.toml`):** id, version, required app API version, entry point, and **permissions** (network,
filesystem scope, compute, GPU). The user approves permissions at install; undeclared access is denied.

**Registry:** same mechanism as components; plug-ins are signed (minisign/sigstore); compatibility checked against
the app version; "verified" mark for plug-ins whose tests pass against published check values.

**SDK:** template plug-in, test kit (check-value harness), documentation; a new model = one file + tests + manifest.

### Add-on roadmap (open implementations of methods that are paid elsewhere)

| Add-on | Commercial counterpart | Method source | Priority |
|---|---|---|---|
| Data evaluation (recommended values with uncertainty) | NIST ThermoData Engine | Published TRC methods; open ThermoML data | High |
| Property estimation for new molecules | Aspen Properties, COSMOtherm | Group contribution, PC-SAFT from SMILES, openCOSMO-RS | High |
| Binary interaction parameter regression | Aspen Data Regression | Standard regression of VLE/property data | High |
| VLE thermodynamic consistency tests | DDBST tools | Herington, Van Ness, point test | Medium |
| Automatic equation search | TableCurve | Symbolic regression (PySR) | Medium |
| Surface fitting with 3D plots | OriginPro | Extension of the fitting engine | Medium |
| Advanced statistics and batch analysis templates | OriginPro, MATLAB toolboxes | Standard statistics libraries | Medium |
| Uncertainty workbench with reports | GUM Workbench | JCGM 100/101 | Medium |
| Molecular simulation link | Commercial suites | LAMMPS (open), Green–Kubo | Later |
| Engineering equation solver | EES | Newton/continuation solvers | Later |

Rule: implement from published methods and open data only; never copy proprietary code, data or databases.

## 2g. Visualizers

| Visualizer | What it shows | Why it helps research | Release |
|---|---|---|---|
| **3D surface viewer** | Property surfaces η(T, p), ρ(T, p), λ(T, p) or the difference between two models; measured points with residual stems; saturation boundary; uncertainty shells; slice planes | Shows at a glance where data sit relative to a model and where models disagree | 0.2 |
| **Experiment visualizer** | Apparatus schematic with live/replayed sensor readings; repeats per state; replay of a measurement campaign | Checks raw measurements and repeatability; teaching and lab reports | 0.3 |
| **Campaign planner** | Measured and suggested states on the p–T map with expected uncertainty reduction | Plans the next measurements where they matter most | 0.3 |
| **Phase-space explorer** | 3D p–ρ–T with saturation dome and critical point; isotherms and isobars as curves | Intuition for where states lie (near-critical, compressed liquid, dilute gas) | 0.2 |
| **Entropy-scaling collapse view** | Many fluids on one reduced-viscosity vs residual-entropy plot; highlight a fluid's deviation | Shows when a fluid (e.g. CF₃I) behaves differently from its family | 0.3 |
| **Uncertainty landscape** | Heat map of model prediction uncertainty over T–p | Where a model can be trusted, and where not | 0.2 |
| **Molecule viewer** | 3D structure from SMILES with PC-SAFT segment representation | Links molecular structure to predicted properties | 0.3 |
| **Data coverage atlas** | Which fluids and properties have data, in which ranges, from how many labs | Finds gaps worth measuring and inconsistent fluids | 0.3 |

Rendering: 3D via WebGL in the Tauri interface (three.js); exports to PNG (up to 2500 dpi), SVG projection, glTF and MP4.

## 2h. Setup builder and CAD simulation

**Setup builder (0.3).** A component gallery (pumps, syringe pumps, valves, capillaries, pipes, heaters, coolers,
plate heat exchangers, vessels, sight glasses, gas cylinders, sensors, data loggers, thermostat baths), dragged onto a
grid canvas and connected with pipes. Each component has physical properties (geometry with uncertainty, material,
thermal expansion, flow model). Uses: (1) publication-quality apparatus diagrams (SVG/PDF), replacing redrawn images;
(2) a **1D loop simulation** (pressure drop, heat balance) to predict and check measured signals; (3) inputs sent
straight to the GUM uncertainty budget; (4) sensors linked to worksheet columns. Templates for common apparatus
(tandem capillary, vibrating wire, transient hot wire, PHE test rig). Users can import their own component libraries.

**CAD and simulation workbench (add-on, 0.4+).** Not a new solver: an integration layer over proven open tools,
run as separate programs (locally or on a remote server):

| Step | Tool | Licence note |
|---|---|---|
| CAD import (STEP, IGES, STL) | OpenCascade (via FreeCAD libraries) | LGPL |
| Meshing | Gmsh | GPL; called as an external program |
| Fluid flow and heat transfer | OpenFOAM | GPL; called as an external program |
| Structural and thermal | CalculiX or Elmer | GPL; called as external programs |
| Post-processing | Built-in viewer; ParaView export | BSD |

GPL tools are invoked as separate executables (no linking), which keeps PropBench MIT-licensed.

**What makes it distinctive:** fluid properties come from validated PropBench models **with their uncertainty**, and
the workbench can run ±U property cases automatically to show how property uncertainty changes the simulation result
(e.g. pressure drop or heat-transfer coefficient). Commercial CFD packages rarely make this easy.

**Scope warning:** this is the largest single feature; schedule it only after beta 0.1 is stable.

**AI CAD and simulation assistant (add-on, after the CAD workbench).**
1. Text or sketch → **CadQuery code** (LLM) → OpenCascade → STEP. Code is shown in the editor; parameters become sliders
   that update without calling the LLM. Code runs in the project's isolated environment.
2. Geometry check loop: closed solid, volume, requested dimensions; optional rendered previews sent back to the model.
3. Simulation setup through **structured tools** exposed by `pb-engine` (mesh, boundary conditions, fluid, run),
   each validated, rather than free-text solver files. Fluid properties always from PropBench models with uncertainty.
4. Nothing runs without user confirmation (geometry, case setup, compute estimate shown first).
5. **MCP server:** `pb-engine` exposes its tools via the Model Context Protocol, so any MCP-capable assistant
   (Claude Desktop, Claude Code, others) can drive PropBench.
6. Reproducibility: prompt, provider, model name and version stored with every AI-generated artefact.

References for design: Text-to-CadQuery (arXiv 2505.06507); Foam-Agent (NeurIPS 2025 ML4PS; arXiv 2505.04997) —
structured, tool-based OpenFOAM automation; CADAM (GPL; ideas only, no code reuse).


## 2i. Thermodynamic backends, models and properties

**Three different things** (the UI keeps them separate): *backends* are software that computes properties; *models*
are the equations of state a backend implements; *data sources* are measured data (ThermoML, WebBook; DIPPR and DDB
are paid). The user chooses a backend, then a model; every property call goes through one `Backend` interface.

| Backend | Licence / access | Models offered (examples) | How connected |
|---|---|---|---|
| **CoolProp** | MIT, bundled | Reference multiparameter EoS (incl. GERG-2008-type mixtures), Peng–Robinson, SRK, PC-SAFT; transport for many fluids | worker (default) |
| **teqp** (NIST) | MIT | Cubic, PC-SAFT/SAFT-VR-Mie, GERG-2008, multiparameter | component |
| **FeOs** | MIT/Apache | PC-SAFT, gc-PC-SAFT, PeTS, UV-theory; entropy-scaling transport | component |
| **thermo** (ChEDL) | MIT | Cubic family, many correlations and compound data | component |
| **REFPROP 10** via **ctREFPROP** | User's own licence; never bundled | NIST reference EoS and transport, mixtures | optional connector |
| **TREND** (Ruhr University Bochum) | User's own licence; never bundled | Multiparameter EoS, mixtures | optional connector (licence terms to check) |
| Clapeyron.jl | MIT (Julia) | Large SAFT/cubic family | later, via juliacall |

**Cross-backend comparison** is a core feature: the property calculator evaluates the same state with several
backends/models and shows deviations from a chosen reference (example, R134a at 300 K, 1 MPa: PR density −2.6 %,
SRK −14.2 %, PC-SAFT +0.07 %; cubic speed of sound −18 %).

**Properties (all workflows are property-independent; viscosity was only the first case):**

| Group | Properties |
|---|---|
| Thermodynamic | density, vapour pressure, saturation properties, enthalpy, entropy, cp, cv, speed of sound, Joule–Thomson coefficient, compressibility factor, fugacity, critical point |
| Phase equilibria | PT/PH/PS flash, bubble and dew points, phase envelopes, VLE/LLE for mixtures |
| Transport | viscosity, thermal conductivity, diffusion coefficients, surface tension |
| Engineering | Prandtl number, refrigeration-cycle quantities (COP, capacity), heat-transfer and pressure-drop correlations |
| Model fitting | any of the above as fitting targets, e.g. PC-SAFT parameters from vapour pressure and density; binary interaction parameters from VLE |

## 3. Build on, not from scratch: decision

| Candidate | Licence | Language | Role in PropBench |
|---|---|---|---|
| **CoolProp** | MIT | C++ / Python | **Core dependency**: reference EoS and transport models; export target |
| **FeOs** | MIT / Apache-2.0 | Rust / Python | **Core dependency**: PC-SAFT, entropy-scaling transport |
| teqp (NIST) | MIT | C++ / Python | Optional backend |
| Clapeyron.jl | MIT | Julia | Inspiration only (Julia runtime too heavy to bundle) |
| thermo (ChEDL) | MIT | Python | Optional: correlations, compound data |
| DWSIM | GPL-3.0 | VB.NET / C# | Inspiration only: plug-in design, CAPE-OPEN; scope is process simulation |
| pychemqt | GPL-3.0 | Python / Qt | Inspiration and **external comparison tool**; **do not copy code** (GPL would bind PropBench) |

**Decision (superseded in part by §0):** a new MIT-licensed application with a **Rust core**, using **FeOs** directly as a Rust crate (PC-SAFT,
entropy-scaling transport, automatic differentiation via `num-dual`) and **CoolProp** through its C++ library via FFI.
The desktop interface uses **Tauri** (Rust backend, lightweight web-technology front end) for native installers on all
three systems. A **Python package built with PyO3** exposes the same core, so researchers can script it and write plug-ins
in Python, and ML models run through **ONNX Runtime** without a Python dependency at run time.

## 4. Architecture

```
propbench/                      Cargo workspace
├── crates/
│   ├── pb-core/        # data model, units (uom), uncertainties, importers (csv, xlsx via calamine, ThermoML via quick-xml)
│   ├── pb-thermo/      # Backend trait; FeOs adapter (native), CoolProp adapter (FFI to libCoolProp), cubic EoS
│   ├── pb-models/      # Model trait; dilute gas, ECS, residual entropy scaling; check values as tests
│   ├── pb-fit/         # least squares (argmin), multistart, scale factors, exact Bayesian linear fits
│   ├── pb-validate/    # LOSO/LOTO/k-fold, physics checks, bootstrap (rayon-parallel), selection rules
│   ├── pb-consist/     # overlap finder, dataset offsets, z-scores
│   ├── pb-ml/          # ONNX Runtime inference (ort); training stays in Python, models exported to ONNX
│   ├── pb-report/      # plots (plotters → SVG/PNG, up to 2500 dpi), docx/markdown/PDF writers
│   ├── pb-export/      # CoolProp JSON, C/Python code, tables
│   ├── pb-engine/      # sidecar process: scheduler, job graph, workers, cache, JSON-RPC server
│   ├── pb-store/       # project file (SQLite), snapshots, audit log, atomic saves, cloud connectors
│   ├── pb-env/         # per-project environments (uv), lockfiles, quotas, process limits
│   ├── pb-vcs/         # Git integration, project mirror, GitHub sign-in
│   ├── pb-ai/          # provider-agnostic AI client, confirmation of proposed changes
│   ├── pb-remote/      # SSH connection to remote engines
│   ├── pb-plugin/      # plug-in host: manifest, permissions, WASM runtime (wasmtime), Python bridge, registry client
│   ├── pb-mcp/         # Model Context Protocol server exposing engine tools to external AI assistants
│   ├── pb-cli/         # `propbench …` command line (clap) — every GUI action available here
│   └── pb-py/          # Python bindings (PyO3 + maturin): scripting and Python plug-ins
├── app/                # Tauri desktop app: src-tauri (Rust commands) + ui (TypeScript, Svelte, uPlot/Plotly)
└── tests/              # integration tests, CF3I regression case, property-based tests (proptest), benches (criterion)
```

Rules: the core crates never depend on the app; every GUI action is a Tauri command calling a core function that is
also reachable from the CLI and Python; heavy work runs on background threads (rayon/tokio) with progress and cancel;
projects are plain files (SQLite via rusqlite + JSON via serde).

**Stack:** Rust (stable) · FeOs · num-dual · nalgebra/faer · argmin · rayon · serde · rusqlite · uom · plotters ·
ort (ONNX Runtime) · clap · PyO3/maturin · Tauri 2 + Svelte/TypeScript · cargo-nextest, proptest, criterion ·
clippy, rustfmt · mdBook docs · GitHub Actions (Windows, macOS Intel + Apple Silicon, Ubuntu).

**Why Rust:** compiled speed (bootstrap and multistart fits parallelised across all cores), memory safety without a
garbage collector, single-binary distribution, and direct reuse of FeOs. **Trade-off:** slower development and fewer
potential contributors than Python; the PyO3 bindings keep the door open for Python users.

## 4a. Storage and sessions

- **Project file = session.** One `.pbp` file (SQLite): datasets and column mappings, model and study settings, results,
  figure definitions, audit log. Large arrays stored as compressed columnar blobs. Each result records code version,
  component versions and seed.
- **Saving.** Autosave; named snapshots; undo history; results written per finished job, so a crash loses nothing and
  an interrupted study resumes. Saves are atomic (write to a temporary file, then rename).
- **Cloud, level 1 — synced folders:** any Google Drive, OneDrive, Dropbox or iCloud folder works; atomic saves keep the
  sync client from uploading half-written files; a lock file warns when the project is open on another machine.
- **Cloud, level 2 — direct connectors (optional components):** Google Drive (OAuth desktop flow, `drive.file` scope:
  only files the app creates), OneDrive, Dropbox. Tokens stored in the OS keychain (`keyring`), never in projects.
- **Sharing.** Reproducibility bundle (project + data + versions); Zenodo export for a DOI; optional Git history.

## 4b. Execution engine

- **Separate process.** The Tauri app launches `pb-engine` as a sidecar and talks to it over JSON-RPC (stdio/IPC). The
  UI never computes; an engine crash cannot freeze the UI or lose saved results. The CLI uses the same engine.
- **Scheduler.** A study becomes a job graph (fits → folds → bootstrap → physics checks → figures) with dependencies.
- **Workers.** Independent jobs run in parallel (`rayon`); progress events streamed; pause, resume, cancel.
- **Content-addressed cache.** Job key = hash(inputs, settings, code version, seed); unchanged jobs are reused.
- **Determinism.** One explicit seed per job derived from the study seed; identical results on all OS.
- **Python helper.** Started only for ML training plug-ins; inference runs in the engine via ONNX Runtime.
- **Later (not v1):** `pb-engine serve` for headless runs on a workstation or cluster, with the desktop app as client.

## 4c. Core principle: isolated project environments

- One environment per project under the app's data folder: Python (managed by `uv`), packages, caches. Nothing is
  installed system-wide; no admin rights; no changes to system PATH or system Python.
- A lockfile in each project pins exact versions; the environment can be rebuilt on any machine.
- Per-environment storage limit, cleanup tool; deleting a project deletes its environment.
- User code runs in a separate process: project folder as working directory, time and memory limits.
- v1 isolates dependencies and processes; container sandboxing (Docker/Podman, if present) is a later option.

## 4d. Collaboration, AI, remote compute, terminal and editor

| Feature | Design |
|---|---|
| **GitHub** | Built-in Git (`gix`/`libgit2`, no Git install needed); GitHub device-flow sign-in; Git-friendly project mirror (settings as text, data as Parquet, results as manifest); meaningful commits; push/pull; Releases for bundles; Git LFS for large data; caches ignored |
| **AI assistant** | Bring your own key; one OpenAI-compatible connector (Groq, OpenRouter, Together, Ollama, LM Studio) plus Gemini and Anthropic; explains results, writes scripts and plot settings, suggests column mappings, drafts report text; never runs code or edits data without a previewed, confirmed change; keys in the OS keychain; clear notice of what is sent; local models for private data |
| **Remote compute** | `pb-engine serve` on a GPU server or workstation; connection over SSH with the user's keys (no open ports); jobs and required data shipped, results synced back; local/remote shown per job; Slurm later |
| **Terminal** | Embedded terminal (xterm.js + `portable-pty`) opened inside the project environment |
| **Code editor** | Monaco editor; Python highlighting and completion; Run executes in the project environment via the engine; `import propbench` scripting API; GUI action recording to scripts |

## 4e. Effortless on every operating system (requirement)

| Area | Requirement |
|---|---|
| **Self-contained** | Installer bundles everything, including a standalone Python (uv / python-build-standalone); users never install Python, Rust or Node |
| **No admin rights** | Per-user install by default; works on locked-down university and company machines |
| **Architectures** | Windows x64 + ARM64 · macOS Apple Silicon + Intel (universal) · Linux x64 + ARM64 |
| **Signed, no warnings (planned, M4d)** | Windows: code signing (SignPath Foundation for OSS, or Azure Trusted Signing) · macOS: Developer ID signing + notarisation (Apple Developer account, ~US$99/yr) · Linux: signed checksums |
| **Install channels** | Now: .msi · .dmg · AppImage/.deb from GitHub Releases, with checksums. Planned (M4d): winget, Homebrew cask, Flathub; download page detects the OS |
| **Web engine** | Tauri uses WebView2 (Windows, bundled bootstrapper), WebKit (macOS), WebKitGTK (Linux; pinned via Flatpak/AppImage) |
| **Updates** | Signed auto-update (Tauri updater) with user consent; release channels stable/beta |
| **Offline and proxies** | Offline installer with common components; system/university proxy settings honoured |
| **Uninstall** | Clean removal; choice to keep or delete projects and environments |
| **Accessibility** | Keyboard navigation, screen-reader labels, high-DPI scaling, light/dark/classic themes, adjustable font size, translatable UI strings |
| **Size targets** | Base installer ≤ 150 MB; components on demand |

**Current status (solo developer, pre-release): installers are NOT yet code-signed or notarised.** Users must
approve the app once on first launch (steps in `docs/getting-started.md`): macOS — System Settings › Privacy &
Security › *Open Anyway*; Windows — SmartScreen *More info › Run anyway*; Linux — make the AppImage executable.
Publish SHA-256 checksums with every release so users can verify downloads. Signing (SignPath Foundation for Windows,
Apple Developer ID + notarisation for macOS) and package-manager listings (winget, Homebrew, Flathub) are planned for
milestone M4d and are not promised before then.

**Release gate:** every release candidate is installed on clean VMs (Windows 11 x64 and ARM64, macOS current and
previous, Ubuntu LTS, Fedora, Debian) with no developer tools, and must pass: install → open CF₃I tutorial → run study
→ export figure → uninstall. Any failure blocks the release.

## 5. Getting started (development)

```bash
# prerequisites: Rust (rustup), Node.js 20+, CoolProp shared library (script provided), Python 3.11+ for bindings
git clone https://github.com/<org>/propbench.git && cd propbench
./scripts/fetch_coolprop.sh            # downloads/builds libCoolProp for this OS (Windows: scripts\fetch_coolprop.ps1)
cargo nextest run --workspace          # all tests must pass before any commit
cargo run -p pb-cli -- --help          # command line
cd app && npm install && npm run tauri dev   # desktop app in development mode
maturin develop -m crates/pb-py/Cargo.toml   # Python bindings into the active virtual environment
```

## 6. Roadmap to beta

| Milestone | Content | Exit test |
|---|---|---|
| **M0 Scaffold** | Cargo workspace, Tauri shell, CoolProp FFI build on 3 OS, CI, clippy/rustfmt, mdBook | Empty app and CLI build and start on all 3 OS in CI |
| **M1 Core (CLI only)** | Data model, importers, CoolProp/FeOs backends, dilute gas, ECS, RES, fitting, LOSO/LOTO, physics checks, bootstrap | **CF₃I regression case reproduces the paper** (below) |
| **M1a Engine and storage** | pb-engine sidecar, job graph, cache, project file with autosave/snapshots, atomic saves | Kill the engine mid-study: UI stays responsive, study resumes with no lost results |
| **M1b Components** | Registry format, downloader with checksum verification, component manager dialog, offline install | Install/remove/update tested on 3 OS without network flakiness (local registry in CI) |
| **M1c Environments** | Per-project environments, lockfiles, limits, terminal in environment | A script that installs packages leaves the system Python and PATH untouched on all 3 OS |
| **M2 Consistency & comparison** | Overlap finder, offsets, z-scores; NIST reference models with check values | CF₃I offset and REFPROP-model numbers reproduced |
| **M3a Worksheets and fitting** | Worksheets (formulas, masks, statistics), general curve fitting with global fits, diagnostics, GUM uncertainty propagation, references | GUM example from JCGM 100 reproduced; global fit recovers known parameters on synthetic data |
| **M3b Graph studio** | Layers, plot types, formatting panel, templates, journal export presets | Every manuscript figure of the CF₃I paper reproduced from the app |
| **M3 Desktop GUI** | Project tree, data grid, fit wizard, validation dashboard, plot panels | GUI smoke tests; a new user completes the CF₃I tutorial unaided |
| **M4 Reports & export** | Report generator, CoolProp export, figure styles | Exported model gives identical values inside CoolProp |
| **M4b Integrations** | GitHub, AI assistant, code editor, remote engine over SSH | AI-proposed change is never applied without confirmation (test); remote job results identical to local |
| **M4c Plug-in system** | Manifest, permissions, WASM host, Python plug-ins, signed registry, SDK and template | A sandboxed plug-in cannot read outside its declared folder (test); template plug-in passes the check-value harness |
| **M4d Distribution** | Signed installers for all OS/architectures, winget/Homebrew/Flathub, auto-update, offline installer, clean-VM release gate | Release gate passes on all listed systems without developer tools |
| **M5 Beta 0.1** | Installers, Python bindings on PyPI, tutorials, contributor guide, plug-in template, ONNX ML models | Beta checklist (section 7) fully green |

## 7. Testing before beta 0.1 (all must pass)

**Scientific correctness (non-negotiable)**
- [ ] Reference check values: NIST NISTIR 8209 CF₃I viscosity 168.5169 μPa·s at 356.8 K, 8.724 mol/L; CoolProp agreement for ≥ 10 fluids
- [ ] ECS conformal mapping residual < 1e-7; Chung dense formula reduces to its dilute-gas limit (ratio 1.0000)
- [ ] **CF₃I regression case** reproduces the manuscript within rounding: ECS ψ+k LOSO 0.54 % / 0.49 %, LOTO 0.68 % / 0.44 %; β₀ = 1.1328, β₁ = −0.0541, k = 1.1540; REFPROP-model AARD 1.08 / 5.49 / 14.79 %; model-free 333 K difference ≥ 4.9 %
- [ ] Property-based tests: fitted models never violate the configured physics checks on random valid states
- [ ] Bootstrap and LOSO results identical for a fixed random seed on all 3 OS

**Software quality**
- [ ] Test coverage of core crates ≥ 85 % (cargo-llvm-cov); zero clippy warnings (`-D warnings`); `cargo fmt --check` clean; no `unsafe` outside the CoolProp FFI module
- [ ] CI green on Windows, macOS (Intel + Apple Silicon) and Ubuntu; Python bindings tested on 3.11–3.13
- [ ] Performance budgets (criterion): 1000 viscosity evaluations < 10 ms; LOSO of the CF₃I ECS model < 1 s; 200-sample bootstrap < 5 s on a laptop
- [ ] Installers (MSI, DMG signed/notarised, AppImage/deb) start on clean machines with no Rust/Python/Node installed; app opens a project in < 2 s
- [ ] GUI never freezes: every computation > 0.2 s runs in a worker with progress and cancel
- [ ] Projects saved by version N open in version N+1 (file-format migration test)
- [ ] Crash handler writes a log and offers a bug report; no data loss on crash (autosave)

**Usability and contribution**
- [ ] Three tutorials (CF₃I viscosity, a well-measured refrigerant, adding a new model plug-in) work end to end
- [ ] A contributor can add a model either in Rust (copy `crates/pb-models/src/template.rs`) or in Python via the plug-in API, and pass its tests without touching other crates
- [ ] CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates, "good first issue" labels in place

## 8. Contributing

Open an issue before a large change. Every model must ship with: (1) a reference or derivation, (2) at least one
published check value as a test, (3) documented validity range. See CONTRIBUTING.md.

## 9. Citation and licence

MIT licence. A software paper is planned for *SoftwareX* or the *Journal of Open Source Software* after beta 0.1;
the CF₃I viscosity study serves as the first case study.
