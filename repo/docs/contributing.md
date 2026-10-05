# Components, plug-ins and contributing

## Principle
Integrate, don't rebuild: use maintained open-source tools with compatible licences (README §0). GPL/AGPL tools run
only as separate processes.

## Adding a model or tool as a plug-in
1. Copy the plug-in template (Python, WebAssembly or Rust).
2. Fill in `plugin.toml`: id, version, required API version, entry point, permissions.
3. Implement the model interface (`fit`, `predict`, `params`, `bounds`, `check_values`, `validity`, `reference`).
4. Add at least one published check value as a test; document the validity range and the reference.
5. Run the test kit; open a pull request.

## Rules
Tests with every change · no copying of GPL or proprietary code · no credentials in project files · AI-proposed
changes are never applied without user confirmation.
