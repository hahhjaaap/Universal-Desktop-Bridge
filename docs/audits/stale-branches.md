# Branch inventory

The snapshot lists all 33 non-`main` branches returned by GitHub on 2026-11-19 before this inventory draft was created. Last commit dates are Git committer dates. An exact tip counts as merged into `main` when it is an ancestor of `6b46d8322b93b56c8ab26a0b49af24d1f51f6880`. A squash or rebase can incorporate an equivalent change without preserving the original tip, so the ancestry result alone cannot authorize deletion. PR evidence is matched by exact head SHA. No branch or tag was changed for this audit.

| Branch | Last commit | Tip | Exact tip on main | Matching PR | Owner decision |
| --- | --- | --- | --- | --- | --- |
| `backup/owner-tools-benchmark-fix-20261105` | 2026-11-05 | `b915053f7` | No | no matching PR found | Keep backup or archive tag with owner approval |
| `backup/pr29-before-sync-009fcc10` | 2026-10-31 | `009fcc107` | No | no matching PR found | Keep backup or archive tag with owner approval |
| `codex/udb-public-policy-docs-20261105` | 2026-11-05 | `7dd83ab75` | No | [#104](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/104) closed, unmerged | Archive tag after owner review |
| `dependabot/github_actions/actions/setup-node-7` | 2026-11-12 | `25be603f4` | No | [#151](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/151) closed, unmerged | Delete candidate after confirming superseding diff |
| `dependabot/pip/reportlab-5.1.0` | 2026-11-12 | `28c833178` | No | [#154](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/154) closed, unmerged | Delete candidate after confirming superseding diff |
| `docs/gui-user-guide-sync-20261101` | 2026-11-01 | `606f5f890` | No | no matching PR found | Archive tag after owner review |
| `feat/cloudflare-access-managed-oauth-readonly-20261103` | 2026-11-03 | `f4ca11b6e` | No | [#66](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/66) closed, unmerged | Archive tag after owner review |
| `feat/enterprise-navigation-shell-20261101` | 2026-11-01 | `9e01fce52` | No | [#43](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/43) closed, unmerged | Archive tag after owner review |
| `feat/gui-activity-approval-diagnostics-20261101` | 2026-11-01 | `bbbad5267` | No | [#49](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/49) closed, unmerged | Archive tag after owner review |
| `feat/gui-security-grant-visibility-20261101` | 2026-11-01 | `7f166710f` | No | [#47](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/47) closed, unmerged | Archive tag after owner review |
| `feature/cloudflare-read-acceptance-gate-20261104` | 2026-11-04 | `6fad6c039` | No | [#93](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/93) closed, unmerged | Archive tag after owner review |
| `feature/owner-device-scope-v1-20261104` | 2026-11-04 | `8e3598b3c` | No | [#92](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/92) closed, unmerged | Archive tag and review migration differences |
| `feature/udb-chatgpt-onecall-roundtrip-20261115` | 2026-11-15 | `92d844f93` | No | [#197](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/197) closed, unmerged | Archive tag after owner review |
| `fix/common-room-open-database-error-dialog-20261103` | 2026-11-03 | `307ebb9c3` | No | [#72](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/72) closed, unmerged | Archive tag after owner review |
| `fix/common-room-stale-ui-when-project-unavailable-20261103` | 2026-11-03 | `d457ca2ba` | No | [#70](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/70) closed, unmerged | Archive tag after owner review |
| `fix/gui-project-grant-refresh-failure-20261103` | 2026-11-03 | `765fadcc7` | No | [#73](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/73) closed, unmerged | Archive tag after owner review |
| `integrate/pr29-on-current-main-20261031` | 2026-10-31 | `37521250e` | No | no matching PR found | Archive tag after owner review |
| `perf/browser-reply-mailbox-wake-20261119` | 2026-11-19 | `5d8482e4a` | No | [#249](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/249) open | Keep for review. Merge only after acceptance |
| `perf/source-file-tools-steps-21-30-20261115` | 2026-11-15 | `96a34e560` | No | [#191](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/191) closed, unmerged | Archive tag after owner review |
| `refactor/cloudflare-only-transport-20261104` | 2026-11-04 | `aa98b2ff4` | No | [#84](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/84) closed, unmerged | Archive tag after owner review |
| `scratch/rebase-verified-submit-196-20261115` | 2026-11-15 | `35a0b41b3` | No | no matching PR found | Archive tag before considering deletion |
| `security/ws10-backend-errors-20261119` | 2026-11-19 | `d727a15de` | No | [#250](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/250) open | Keep for review. Merge only after acceptance |
| `security/ws12a-access-characterization-20261119` | 2026-11-19 | `c7ae18d13` | No | [#251](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/251) open | Keep for review. Merge only after acceptance |
| `security/ws12b-access-hardening-20261119` | 2026-11-19 | `37fdcedff` | No | [#252](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/252) open | Keep for review. Merge only after acceptance |
| `security/ws13-relay-audit-20261119` | 2026-11-19 | `4d6be3e76` | No | [#253](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/253) open | Keep for review. Merge only after acceptance |
| `security/ws14-execution-audit-20261119` | 2026-11-19 | `82a6ee202` | No | [#254](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/254) open | Keep for review. Merge only after acceptance |
| `security/ws15-native-shutdown-evidence-20261119` | 2026-11-19 | `b26415197` | No | [#255](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/255) open | Keep through native diagnosis |
| `udb/p0a-59-tool-registry-20261108` | 2026-11-08 | `9683f47fe` | No | [#133](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/133) closed, unmerged | Archive tag only after owner compares D1 and catalog work |
| `udb/p0c-tenant-auth-staging-20261108` | 2026-11-08 | `0da56656e` | No | [#132](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/132) closed, unmerged | Archive tag only after owner compares D1 and catalog work |
| `udb/p0d-d1-verified-mcp-staging-20261108` | 2026-11-08 | `e7c46d00e` | No | [#134](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/134) closed, unmerged | Archive tag only after owner compares D1 and catalog work |
| `udb/p0e-59-tools-d1-integration-20261108` | 2026-11-08 | `14c542a0c` | No | [#135](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/135) closed, unmerged | Archive tag only after owner compares D1 and catalog work |
| `udb/resolve-pr171-after-169-20261114` | 2026-11-14 | `bb36740b2` | No | no matching PR found | Archive tag after owner review |
| `udb/steps-01-30` | 2026-11-08 | `d060f743f` | No | no matching PR found | Archive tag only after owner compares D1 and catalog work |

## D1 and historical branches

- The snapshot contains `udb/p0a`, `udb/p0c`, `udb/p0d`, and `udb/p0e` heads with distinct tool catalog, tenant auth, and D1 staging or integration work. No `udb/p0b` or `fix/p0b-authenticated-edge-mcp-discovery-20261107` ref was present. PR #133 used the latter as its base. Verify the D1 migration and tenant isolation differences before retiring these branches.
- The older `feature/owner-device-scope-v1` tip remains separate from `main`. Compare its migration and owner-proof assumptions to the current Access/account Fleet routes. A similarly named feature in `main` does not prove the branch is redundant.
- Review the verified-submit scratch rebase and historical backup tips for useful diffs before deletion. An archive tag preserves reachability without retaining a working branch.
- Current `main` already pins setup-node v7 and reportlab 5.1.0. The listed Dependabot heads are cleanup candidates after confirming the exact superseding file changes.
