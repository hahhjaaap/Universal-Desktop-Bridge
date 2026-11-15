# UDB host mailbox performance and safety (separate change)

> This document is **not the authoritative 100-step per-tool UDB roadmap**.
> This draft originally used an incorrect step range. The user established
> a separate 100-optimization roadmap that has reached step 40.

## Implemented changes and verification goals

- Filter JSON command candidates before sorting, preserving Windows/POSIX suffix rules and single `os.listdir` traversal.
- Keep command polling read-only: the listing never opens, executes, retries or claims commands.
- Use a `scandir` pass to prune eligible replies older than 120 seconds, preserving other files and folders.
- Refuse redirected reply directories using `reject_links`; never follow symlink entries or touch symlink targets.
- Compare previous and revised mixed-inbox timing with synthetic disposable fixtures only; do not extrapolate to end-to-end UDB latency.
- Gate merge on Linux/Windows Python and frozen EXE CI; no user installation or Cloudflare deployment.

## Focused checks

```sh
python -m pytest -q tests/test_host_mailbox_optimization.py tests/test_proxy_parallel_idle_performance.py
python tools/benchmark_hotpaths.py --samples 5 --backend-delay-ms 10
python -m ruff check src/udb/host_service.py tests/test_host_mailbox_optimization.py tools/benchmark_hotpaths.py
```
