# How a study works

- **Project file (`.pbp`).** One file holds datasets, mappings, models, studies, results, figures and an audit log.
  Autosave, snapshots and undo. Saves are atomic, so cloud-synced folders are safe.
- **Isolated environment.** Each project has its own environment in the app data folder; nothing is installed
  system-wide.
- **Engine.** Computation runs in a separate engine process. A study becomes a job graph (fits → folds → bootstrap →
  physics checks → figures) run in parallel, cached by a fingerprint of inputs, settings, code version and seed.
- **Validation.** Models are judged on states they were not fitted to (leave one state out, leave one temperature out),
  by physics checks outside the measured range, and by bootstrap uncertainty bands.
- **Selection rule.** Fixed and locked before fitting; changing it starts a new study.
- **Uncertainty.** Stated uncertainties are carried from import to fitting weights, GUM budgets and prediction bands.
