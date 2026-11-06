# P0-B owner-attended staging acceptance checklist

This gate is a **local schema checker for a redacted, manually reviewed
acceptance checklist**. It does not perform OAuth, verify signatures, deploy
a Worker, inspect live Windows project files or independently authenticate
the claims in the supplied report.

Use it only **after** the separately staged Worker and independently
registered device have been reviewed and tested by the actual owner. Nothing
in this document authorizes replacing existing `cloud-pairing.json` or
changing a production Cloudflare Worker.

## Usage

Create a local file outside the Git checkout. Do not commit the checklist:
even non-secret deployment revision IDs can be useful to attackers when
combined with other metadata.

```shell
python tools/check_p0b_staging_acceptance.py C:\temp\redacted-staging-check.json
```

The file must have exactly this shape (the example is deliberately **blocked**):

```json
{
  "schema_version": 1,
  "environment": "isolated-staging",
  "source_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "worker_revision": "bbbbbbbb",
  "checks": {
    "owner_attended": false,
    "verified_oauth_chatgpt_read": false,
    "fixture_content_sha256_match": false,
    "only_granted_read_tools_listed": false,
    "two_owners_verified": false,
    "two_devices_verified": false,
    "reconnect_without_replay": false,
    "ten_concurrent_reads_matched": false,
    "eleventh_concurrent_read_rejected": false,
    "mutations_exclusive": false
  },
  "denials": {
    "wrong_identity": false,
    "wrong_device": false,
    "protected_path": false,
    "revoked_grant": false,
    "write_or_desktop": false
  },
  "networks": {
    "network_a": {"attempted": 0, "matched": 0},
    "network_b": {"attempted": 0, "matched": 0},
    "network_c": {"attempted": 0, "matched": 0}
  }
}
```

Replace placeholder commit/revision values **locally**, review all fixture
read, SHA-256, discovery, deny, revocation, reconnect and concurrency records,
then set only independently observed booleans to true. Use three distinct
approved network conditions, with at least 30 authenticated scoped reads and
all expected matches per condition. Record *counts only*; do not put owner
emails, device IDs, auth headers, network addresses, project paths, document
contents, token hashes or secrets in this report.

The checker returns `blocked` and constant identifiers for incomplete
checks; extra fields, malformed types, symlinked or oversized JSON fail
closed. It never prints submitted revisions or file content. Its success
result is called `checklist_complete`, **not** `security_approved`, because
a filled JSON file is a self-attestation and can be falsified. Preserve
separate private test evidence and obtain independent review under
[Issue #95](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/95).

## Release gate

This **does not** override the public-release roadmap, owner approval,
Authenticode signing, privacy/legal decisions or independent cross-tenant
review. A complete checklist must never be interpreted as permission to
enable remote desktop execution or production writes. Keep Issue #118 open
until authenticated ChatGPT ↔ Cloudflare ↔ Windows evidence exists.

Related: [P0-B acceptance runbook](cloudflare-project-read-acceptance.md)
and [release roadmap](public-release-plan.md).
