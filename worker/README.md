# propbench (Python worker)

The science side of PropBench. The desktop app's `pb-engine` starts this package as a worker process
(`python -I -B -X utf8 -m propbench.worker`) and talks to it over JSON-RPC 2.0 on stdio. See the repository README §0
and §4b.

```bash
uv sync --project worker
uv run --project worker pytest worker
```
