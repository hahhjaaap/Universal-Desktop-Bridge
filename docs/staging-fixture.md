# Offline synthetic fixture for Cloudflare scoped-read acceptance

This is a **staging-only** test project generator for issue #94. It cannot
deploy the Cloudflare Worker, grant access, authenticate ChatGPT, or prove that
the Windows device is reachable. Do not run the acceptance against real
customer data or the production Worker.

## Create disposable local fixtures

Run with the Python source checkout on a Windows device that will be used for
the **separate staging** connection. Choose a NEW absolute directory whose
parent already exists (example uses an explicitly chosen test folder):

```powershell
python tools/prepare_staging_fixture.py --root C:\\udb-staging-fixture-2026
```

The command refuses an existing destination and never overwrites it. It creates:

| Local path under `--root` | Expected test |
| --- | --- |
| `project/README.md` | Allowed scoped `read_file` with matching SHA-256 |
| `project/probe.py` | Allowed `check_python_syntax` and optional read |
| `project/.env` | Protected-path read must be denied |
| `outside.txt` | `../outside.txt` must be denied from the registered project |
| `manifest.json` | Expected SHA-256 hashes and relative paths; no secrets |

All content is **synthetic**. Store this fixture separately from owner projects.
Only register the `project` directory in UDB as
`udb-staging-fixture` with **read-only** project permission. Do not register
the parent directory or grant arbitrary host access.

## Manual owner-attended acceptance

1. Review/pin the Worker source SHA and deploy a **separate staging Worker**,
   with staging OAuth Access policy and read-only per-subject/device grants.
2. Run the existing public preflight
   `check_cloudflare_deployment.py --require-project-read`; it must pass.
   Its success is still **not** proof of authenticated reads.
3. Connect the staging Windows cloud agent and ChatGPT using the owner's
   authenticated staging connection. Confirm the tool catalog is scoped
   to the explicitly approved read-only tools.
4. Call `read_file` for `udb-staging-fixture` / `README.md`. Compare the
   returned relative path and SHA-256 with `manifest.json`, and compare
   its text locally. Optionally check `probe.py` syntax.
5. Call `read_file` against `.env` and `../outside.txt`; both must
   be **denied**. Verify wrong-subject, wrong-device, grant-revoke,
   OAuth-expiry and disconnect/reconnect cases per the main acceptance
   runbook. A successful fixture read alone does not establish those.
6. Repeat the authorized read matrix and record only reviewed deployment
   SHA, result codes, tool names and expected/observed synthetic hashes.
   Never include device tokens, OAuth credentials, subject identities,
   private grant JSON or unrelated file contents in a public issue.

See [Cloudflare project-read acceptance](cloudflare-project-read-acceptance.md)
and [owner/device isolation](owner-device-isolation.md). Keep #94 open until
real authenticated access, denial, revocation and reconnect have been proven.
