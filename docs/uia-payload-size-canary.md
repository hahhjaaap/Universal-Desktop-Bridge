# Read-only UIA snapshot payload-size canary

This report adds **aggregate serialized-result byte counts** to the existing
Windows **test-owned WinForms** UIA cache comparisons. It helps investigate
[HyperSpeed 2.0 issue #211](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/211)
step 38 without retaining accessible names, text, child identifiers, window
titles or personal desktop data in the report.

Run from a source checkout with the existing Windows test prerequisites:

```powershell
python -m tools.compare_uia_snapshot_cache --warm --samples 30 --sizes 50 500 1000 --output reports/uia-warm-payload.json
python -m tools.compare_uia_snapshot_cache --dynamic-recreate --samples 10 --sizes 50 500 1000 --output reports/uia-recreate-payload.json
```

Each result contains `payload_bytes.cached` and
`payload_bytes.uncached` with `p50_bytes`, `p95_bytes` and
`max_bytes`. These counts are computed by serializing **only the parsed
result object** using compact, ASCII-escaped JSON. They exclude the
persistent-worker sequence envelope and the newline/frame overhead, and
are therefore **estimated result JSON UTF-8 bytes, not network bytes or
actual PowerShell stdout size**.

The calculation is performed **outside** the timed call, so it does not
inflate existing snapshot latency measurements. Warm/dynamic reports
exclude initial cold samples. A cached/uncached result still must pass
exact content parity and password-redaction checks; no payload body enters
the aggregate report.

Compare payload sizes with latency p50/p95 and truncated-sample counts,
using the same source build and fixture sizes. A smaller payload alone is
not proof of lower CPU, working-set/RSS or end-to-end ChatGPT latency.
Those require separate measurements on authorized Windows environments.
Do not enable persistent UIA on a customer's computer as part of this canary.
