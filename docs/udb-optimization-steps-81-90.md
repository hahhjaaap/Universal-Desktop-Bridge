# UDB 100-step optimization roadmap — implementation group 81–90

**State:** code and regression tests proposed; CI and merge pending.
This follows the per-tool inventory in [PR #194](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/194).
Historical steps 31–40 have not been independently reconciled.
This group does not touch the user's machine or install/release UDB.

| Step | Public tool or operation | Focused improvement | Required invariant |
| ---: | --- | --- | --- |
| 81 | `file_read_chunk` | Check page envelope before scoped-path I/O, calculate one stat-derived version/identity and compare live opened file metadata | Same base64, chunk SHA256, 16-GiB cap and changed-file rejection |
| 82 | `file_upload begin` | Validate declared size/hash before protected path traversal and avoid repeated integer conversion | Create-only, two-upload cap, no overwrite, scoped destination |
| 83 | `file_upload write` | Validate bounded base64 payload and expected cursor before stage I/O; one stat for stage checks | No duplicate offsets or writes; max 1 MiB/chunk and original stage identity |
| 84 | `file_upload abort / commit cleanup` | Cleanup helper checks stage identity using one stat rather than existence plus multiple stats | Never unlink a file replaced concurrently; commit still re-hashes bytes and fsyncs before atomic publish |
| 85 | `file_operation copy/move` | Reuse one scoped source metadata stat to classify path and capture its identity | 20,000 entries/16 GiB cap, per-entry guard, verified copy, no overwrite, cancel/commit boundaries |
| 86 | `spreadsheet inspect/read` | Preflight read range before parsing workbook and format/count long text in one pass | Same 5,000-cell page, 2,000-char clipping and no formula evaluation |
| 87 | `spreadsheet write/edit_cells` | Preflight edit-cell shape and addresses before workbook load; cache formula flag per operation | 10,000-cell edit cap, XLSX bounds, formula safety and scoped commit |
| 88 | `spreadsheet audit_invoices/export_audit` | Normalize column selector once and emit report row numbers without repeated worksheet size probes | Decimal accounting semantics, duplicate warnings, safe literal cells and review-only disclaimer |
| 89 | `word_document read` | Stream selected body/table paragraph window rather than allocating a list of all paragraphs | Full total/offset/truncated index parity, 200-item page cap, Unicode content |
| 90 | `pdf_document inspect/read/merge` | Preflight page-window constraints and cache each parsed source page collection | 200-page aggregate cap, encrypted-PDF rejection, page order, no OCR or write-permission expansion |

## Verification, compatibility and security

- Tests: `tests/core/test_tool_optimization_81_90.py` plus existing
  companion, document, upload, rollback and bridge security suites.
- Run full CI on the final SHA: Linux/Windows Python 3.11 and 3.12, Ruff,
  Windows frozen EXE, catalog parity and Cloudflare private relay.
- The source worker still checks scoped input hashes and output staging
  identities. File upload and move/copy still require owner-approved project
  access and reject overwrite.
- A faster local checksum or parsing path is **not** an excuse to remove
  read-after-write validation, cancel checks, approval or recovery guards.
- Benchmarks on authorized Windows hardware should separately compare
  p50/p95 and memory with real fixture sizes; code-level reductions alone
  do not prove end-to-end 5–6-second tool calls.
