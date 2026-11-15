# UDB 100-step roadmap: implementation group 51–60

This group implements the **proposed** tool-by-tool milestones in
[the inventory](udb-100-tool-optimization-inventory.md). It does not infer
a missing mapping of historical steps 31–40. All changes are isolated from
the user's installed Windows desktop and Cloudflare deployment.

| Step | Tool/action | Narrow change | Regression / boundary |
| ---: | --- | --- | --- |
| 51 | `computer_process start` | Construct executable Path once; reject bool timeout before expensive PATH/FS calls | Invalid durations never spawn; absolute paths do not use PATH; owner executable allowlist unchanged |
| 52 | `computer_process read` | Avoid opening log at exact 4-MiB EOF quota, retain bounded output/cursor | Fake inaccessible log; strict offset bound and no unknown-job/foreign-PID read |
| 53 | `computer_process list` | Optional `limit=1..30` to materialize/transport fewer owned metadata rows | Default 30 and legacy insertion order; no OS-wide enumeration |
| 54 | `computer_process stop / cleanup` | Clear capacity slot reference after successful close, avoiding repeat release in cleanup retry | Fake double finish; no arbitrary PID termination |
| 55 | `computer_desktop list` | Reuse one title/class/foreground observation per enumerated HWND | Window IDs still live 60s; `resolve` still checks live PID/class/focus |
| 56 | `computer_desktop screenshot` | Convert top-down BGRX directly to PNG scanlines; no `buffer.raw` and extra full RGB buffer | Pixel/CRC fixture, max dimensions, bounded peak memory; foreground/occlusion verification untouched |
| 57 | `computer_desktop read_text` | Compact UIA JSON envelopes and avoid `.strip()` copy on successful responses | Same 1–5000 limit, Unicode and password-field restrictions |
| 58 | `computer_desktop UIA mutations` | Reuse fixed helper path and skip JSON decode after nonzero exit | No fallback input/elevation; unknown outcome never replayed |
| 59 | `clipboard_set` | Preflight malformed `expected_version` before initializing the input observer | Valid requests retain fresh owner pause and CAS-version verification |
| 60 | `apps / launch_app` | Normalize requested name once, stop on second ambiguous exact match | No fuzzy name launch; fresh app enumeration and owner pause preserved |

## Verification and merge gates

- Synthetic tests: `tests/core/test_windows_optimization_51_60.py` and existing
  `tests/core/test_computer.py`, `tests/test_windows_workflow.py`.
- Linux + Windows Python 3.11/3.12, full simulation/scenario suite, Ruff,
  generated Cloudflare catalog parity, EXE freeze and installer rollback must
  pass on the **same final head SHA**.
- Measure p50/p95 with an owner-approved real Windows fixture **separately**
  before claiming full-machine responsiveness. Synthetic memory tests validate
  an algorithmic improvement but cannot prove 5–6-second end-to-end desktop
  execution over Cloudflare/ChatGPT.
- Preserve local pause, explicit grant, per-call process and window identity,
  no overwrite, no command replay, and no deployed-state claims.
