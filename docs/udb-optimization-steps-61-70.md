# UDB optimization program — implementation proposal 61–70

> **Scope:** host session, owned browser, captured-image cache, file transfer
> and virtual pointer. These steps belong to the proposed 100-step inventory
> in [PR #194](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/194).
> Exact historical 31–40 mapping remains unverified. This document does **not**
> claim that the changes are shipped or installed on any user's machine.

| Step | Tool or action | Change on this PR | Required invariant |
| ---: | --- | --- | --- |
| 61 | `host_start_session` | Reject bool/non-integer duration early, reuse exact expiry in response | No unauthorized session allocation; bounds 60–1800s unchanged |
| 62 | `host_workspace read` | Eliminate first of two `validate()` calls; `message()` retains immediate live HWND/Edit identity check | Same readback and no-activation guarantee |
| 63 | `host_close_session` / maintenance | Sample owner enablement and time once per bounded sweep, not per owned session | Every external dispatch remains independently grant-checked; monitoring still revokes |
| 64 | `browser list` | Sanitize each page target URL once, share result across adoption and list response | Still closes unsafe URLs and excess tabs; no user-browser adoption |
| 65 | `browser element` / locator | Compile static placeholder regex once per module | No user interpolation or unsafe selector execution, no action replay |
| 66 | `browser screenshot` | Resolve owned CDP session once for identity and screenshot | Same 8-MiB limit, isolated profile and CDP deadline |
| 67 | `browser capture_stop` | O(1) exact stream removal instead of scanning all streams | Whole-session stop still clears all session streams; maximum four |
| 68 | `browser upload` | Reject malformed local payload/selector before CDP origin round trip | Valid uploads still check same-origin *before* selecting files; 8 MiB cap |
| 69 | `browser freeze` / lifecycle | Resolve owned CDP session once per page for pause and lifecycle update | Per-tab failures still tracked; no user session/profile access |
| 70 | `virtual_pointer` | Reuse immutable Win32 LASTINPUTINFO ctypes structure layout | Real system cursor never moved; foreground/owner input checks unchanged |

The code changes here are deliberately narrow. The original roadmap's larger
ideas (browser warm start, upload streaming, optimized navigation and DOM work)
remain separate follow-ups requiring direct performance evidence, not a claim
that those complex areas were completely optimized by these microchanges.

## Verification

- `tests/core/test_optimization_61_70.py` covers fast paths and safety
  failures using disposable state and fake CDP/Win32 objects.
- Run Linux and Windows Python 3.11/3.12, Ruff, source/package checks,
  cloud relay, frozen Windows EXE, security and installer rollback CI.
- Perf claims are limited to reduced allocations, repeated validations, and
  calls verified by tests. No end-to-end desktop latency figure is asserted.
- Never bypass owner approval, access revocation, origin checks, password or
  input protections, or replay side-effecting UI actions after uncertainty.
