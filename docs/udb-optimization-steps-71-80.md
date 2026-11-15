# UDB per-tool optimization group 71–80

**Status:** implementation proposal, pending CI and merge. This group follows
[the 100-step inventory draft (PR #194)](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/194).
Historical steps 31–40 have not been independently reconciled. These are
bounded micro-optimizations, **not** claims that complete terminal, search,
or recovery subsystems are now globally optimal.

| Step | Tool / operation | Change | Safety acceptance |
| ---: | --- | --- | --- |
| 71 | `terminal_start` | Validate bounded argv, program, duration, memory and mode before resolving a scoped cwd or executable; resolve requested Path once | Invalid requests never claim a slot or start a shell; owner `--enable-terminal` gate unchanged |
| 72 | `terminal_list` | Stream per-session status strings to join without materializing an extra list | Poll only Companion-owned processes; retain insertion order and output |
| 73 | `terminal_read` | Skip incremental UTF-8 decoder initialization on empty idle reads | Maintain byte offsets, partial multibyte handling, base64 output and bounded 10 KiB pages |
| 74 | `terminal_send` / `terminal_interact` | Encode Unicode input exactly once, short-circuit over-limit code point length | Queue max 4, no duplicate input, strict 10,000-byte limit and no command replay |
| 75 | `terminal_stop` / finish I/O | Release the claimed terminal slot once after successful close | Always close owned process; retain stop/status semantics and cleanup on exit |
| 76 | `search_start` / worker | Preflight query, timeout and type before path traversal; reuse scoped path validator once per worker | Preserve file/CPU/time limits, protected roots and no host permissions |
| 77 | `search_read` | One owned-task dictionary lookup for progressive read/cancel, bypass journal only for live job | Past-job offset paging and persistent journal replay policy unchanged |
| 78 | `search_stop` | Avoid repeated dirty journal marks for repeated cancellation while still reattempting worker termination | Cancel never claims success before job exits; partial results remain readable |
| 79 | `file_search` with context | Precompute casefolded literal query and parent folder path per directory | Exact context/line numbering, hidden folder exclusion, regex vs literal semantics unchanged |
| 80 | `work_recovery inspect` | Read live owned job or terminal directly, skipping stale journal decrypt; reject unknown actions before journal I/O | Interrupted records still require lease checks; no replay of side-effecting work |

## Verification gates

- Test fixtures are fake Companion sessions, fake workers and a temporary scoped
  folder: `tests/core/test_tool_optimization_71_80.py`.
- Required CI: Linux and Windows Python 3.11/3.12 regression suites; Ruff;
  Windows frozen EXE/update-rollback checks; generated tool catalog parity;
  Cloudflare private relay checks.
- No shell, real Windows input, Cloudflare deployment or installer action was
  performed on the user's machine. A claim of end-to-end speedup requires a
  separate authorized benchmark on the intended PC and a real tool call path.
- Terminal commands, file mutations, search worker side effects and interrupted
  jobs must never be automatically replayed after uncertain execution.
