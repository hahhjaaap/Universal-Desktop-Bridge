# Current UDB source and Windows release

| Surface | Status when preparing v0.14.0 | How to verify |
| --- | --- | --- |
| Candidate source | 0.14.0 on `release/0.14.0` | `git rev-parse HEAD` and `src/udb/_version.py` |
| Published Windows release | v0.13.0 | [GitHub Releases](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases) |
| Installed Windows executable | Per device | `udb version --json` and `udb doctor --json` |
| Cloudflare relay and ChatGPT | Per deployment and grant | Worker deployment identity, MCP discovery, and an authorized read-only call |

The Windows CI job for 0.14.0 downloads and checks the pinned v0.13.0 installer and ZIP, installs into disposable directories, then exercises a real version upgrade and rollback against the built candidate. Its offline pairing fixtures cover file preservation. A separate paired Windows test is required to prove that device identity, authorization and ChatGPT connectivity survive the update.

## Release approval

The repository owner dispatches `one-command-windows-release` from `main` after reviewing the external acceptance evidence. The workflow requires successful push runs of package/regression CI, CodeQL and the runtime dependency audit for the exact current `main` SHA. It rejects an existing release or a conflicting tag. Frozen and installer checks run before creating and verifying provenance for the assets. See [release verification](release-security.md).

Before dispatch, record Windows 10/11 acceptance, including 0.13.0 → 0.14.0 → 0.13.0 on an isolated paired device. Check the device identity, access scope, a permitted MCP call, and restoration of the previous EXE after rollback. Keep the test identity and data home separate from production.

For the latency gate, use an isolated Windows x64 staging machine, the same Chrome version, and one authorized fixture and network path for both exact builds. Time 50 or more trials per build from ChatGPT tool submission until it receives the final verified outcome. Use unique request IDs for each trial, interleave baseline and candidate samples, record errors and timeouts, and report nearest-rank p50/p95/p99 and error rates. Capture cold startup separately. The release requires an end-to-end candidate p95 of at most 6 seconds. The FastPath PR also requires at least a 40% p95 reduction plus permission, navigation and no-replay parity. The 50-sample Windows mailbox benchmark excludes ChatGPT and Cloudflare. See [the end-to-end fixture and scoring procedure](fastpath-e2e-acceptance.md).

See [v0.14.0 candidate changes](release-notes.md) and [v0.13.0 release history](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases/tag/v0.13.0).
