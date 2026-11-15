# UDB optimization roadmap: steps 30–40 (2026-11-15)

> This is the **30–40** phase requested by the owner, not steps 21–30.
> The exact historical descriptions for each number could not be independently
> recovered. The scoped work below derives from the existing
> `docs/optimization-audit-2026-11-14.md` and current host-worker hot paths.
> Statuses describe code/test additions, **not** successful CI or installed builds.

## Acceptance inventory

| Step | Implementation/acceptance goal | Current evidence |
| --- | --- | --- |
| 30 | Establish disposable, reproducible idle/mixed mailbox performance baseline | Existing `tools/benchmark_hotpaths.py` extended with mixed-mailbox comparison; numbers must be measured per machine |
| 31 | Avoid sorting unrelated files when polling command inbox | Code in `pending_inbox_commands` now filters JSON candidates before sorting |
| 32 | Preserve Windows case-insensitive `.JSON` detection | Regression test added, executed by Windows CI when green |
| 33 | Preserve POSIX case-sensitive `.json` detection | Regression test added, executed by Linux CI when green |
| 34 | Keep exactly one directory listing and do not open/execute pending commands | Regression tests for one `os.listdir` and no `Path.open` added |
| 35 | Replace repeated reply glob/stat with bounded-on-entry `os.scandir` metadata | `_prune_replies` updated |
| 36 | Refuse redirected reply entries during cleanup | `DirEntry.is_file(follow_symlinks=False)` and `reject_links(folder)`; regressions cover both linked files and a replaced linked directory |
| 37 | Preserve 120-second reply expiry and cleanup error isolation | Regression covers stale/fresh replies, unrelated names, directories and a missing folder |
| 38 | Compare old vs new mixed-inbox paths without user files | Informational benchmark now includes both latencies and exact result parity |
| 39 | Pass full Windows/Linux Python CI, lint, packaging and security regressions | **Pending** GitHub Actions; never claim success from merely adding tests |
| 40 | Review against release/rollback policy, then conditionally merge | **Pending** PR review, CI and verified Windows packaging; production stays untouched |

## Non-negotiable behavior

- The original host worker validates every command path and atomically claims a
  pending command before execution. Listing must neither read nor execute it.
- Do not replay commands with uncertain outcomes, bypass path or owner checks,
  weaken grants/CSRF/secret redaction, follow Windows reparse points or delete
  user data.
- Preserve the **0.25-second** idle poll, **5-second** reply cleanup cadence and
  **120-second** reply retention cutoff; changes here do not modify scheduling.
- `os.scandir` metadata checks do not grant file permissions. The cleanup
  avoids symlink targets and refuses non-regular entries.
- Benchmark measurements are synthetic; never present them as real Windows
  computer or end-to-end ChatGPT latency.

## Test commands

```sh
python -m pytest -q tests/test_host_mailbox_steps_30_40.py tests/test_proxy_parallel_idle_performance.py
python tools/benchmark_hotpaths.py --samples 5 --backend-delay-ms 10
python -m ruff check src/udb/host_service.py tests/test_host_mailbox_steps_30_40.py tools/benchmark_hotpaths.py
```

**Release gate:** leave this PR as draft until Windows and Linux test jobs,
Windows frozen-build and rollback tests, and security invariants all pass.
No local Windows device, installed UDB executable, Cloudflare Worker, account
tokens or user project data is modified by this branch.
