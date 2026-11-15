# UDB source/file tools — optimization roadmap, steps 21–30

> Status: implementation in progress on a **stacked draft branch based on PR #188**. This document is a newly defined continuation of steps 11–20; it is **not** a recovered, previously approved 21–30 specification.

## Constraints
- Maintain current MCP tool names, response keys, UTF-8 page offsets and source-write approvals.
- Validate every returned/opened path using the existing project/owner policy. Do not cache authorization.
- No Cloudflare deployment, Windows privileges, tokens, data migrations or production-machine changes.
- Never traverse protected trees, symlinks, reparse points or hardlinked data.
- Validate both Windows and Linux, Python 3.11/3.12, Ruff, catalog parity, frozen Windows build and rollback before merge.

| Step | Target | Acceptance criterion |
| --- | --- | --- |
| 21 ✅ Code + regression added; CI pending | Search byte budget preflight | Do not open the next candidate file after its size would exceed the 4-MiB search byte budget; report `byte_budget` explicitly. Retain the existing 512-KiB source-read cap. |
| 22 ✅ Code + regression added; CI pending | Search result determinism | Same unchanged project tree yields stable matches and line numbers without materializing an unbounded directory listing. |
| 23 ✅ Regression added; CI pending | Search error isolation | Failed UTF-8 decoding, disappeared files and permission revocation never expose forbidden content or abort unrelated safe matches. |
| 24 | Batch read deduplication | Repeated paths retain repeated ordered output while avoiding redundant physical reads **only if** project policy and audits remain per-request and revocation-safe. |
| 25 ✅ Regression added; CI pending | Batch read output budget | Exact UTF-8 byte count, preflight + post-read limits, and no partial response on overflow or revocation. |
| 26 ✅ Regression added; CI pending | File listing pagination | Stable offset and keyset behavior on mixed-case names, ties and insertions, with explicit 10k scan truncation. |
| 27 ✅ Regression added; CI pending | UTF-8 page boundaries | Exact byte offsets across 1–4 byte characters; reject continuation-byte offsets and malformed content. |
| 28 ✅ Regression added; CI pending | Line reader scalability | Stream bounded-memory line pages including CRLF, Unicode separators, very long lines and large offsets. |
| 29 ✅ Regression added; CI pending | Source edit concurrency | Expected SHA and occurrence count gate writes; no partial writes on mismatch; preserve owner approvals/backups. |
| 30 | End-to-end regression and benchmark gate | Add paired baseline/new benchmarks and cross-platform CI; **only** merge after all required checks complete successfully. |

## Dependency / release sequence
1. Complete and merge PR #188 after its draft status, Windows/Linux CI, frozen executable and rollback tests have been cleared.
2. Implement and review steps 21–30 in this branch; target PR #188's branch until it is merged, then retarget to `main`.
3. Run catalog parity and the full regression matrix; investigate failures, avoid bypassing protections.
4. Merge only after approval/required CI; roll out to staging first. Actual UDB installs, user files, cloud deployments and production remain unchanged until separately authorized.

## Verification record
- Roadmap authored: 2026-11-15.
- Desktop Commander devices `hahhjaaap` and `DESKTOP-D07U6V5` were offline when checked; live Windows acceptance was not available.
- Each implementation step must be marked complete only with a code change/test result or a concrete existing regression covering the criterion.
