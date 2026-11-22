# FastPath end-to-end acceptance

Use an isolated Windows 10/11 staging device and Cloudflare connection with an
attended owner grant for UDB's owned browser. Use disposable browser profiles
and a staging HTTPS origin. Keep the active installation, primary pairing, and
production Cloudflare configuration outside the test.

## Prepare the run

- Serve [the pagination fixture](../examples/staging/fastpath-pagination.html)
  on the staging origin and record the page file's SHA-256. The test page has
  no form, external resource, account data, or server-side mutation.
- Record the exact Windows artifacts and source revisions. For PR #262 use
  the PR base and head builds with the same Windows, Chrome, staging Worker,
  access scope and network path. For release acceptance use the published
  baseline and the exact release candidate. Record the Windows/Chrome versions
  and deployed Worker revision in the private run notes.
- Verify both artifact identities through `bridge_status` from the staging
  ChatGPT connection. Check catalog visibility and the attended background
  grant on each staging identity. For FastPath, confirm the candidate accepts
  `click_postcondition` on an owned-browser FastPath step. Use one active
  agent for a given pairing. Build switches and warmup are outside the timed
  window.

## Record the trials

Before each trial, reopen the fixture in an owned tab and observe `Page 1`.
Submit one `host_browser(action="fastpath")` request through ChatGPT, using the
owned session/tab and a fresh request ID. Use five `click` steps on
`#next` followed by `wait_for` on `#page`, `state="text"`,
`value="Page 6"`. For the FastPath candidate add
`click_postcondition={"selector":"#page","text":"Page N"}` to each click, with
`N` from 2 to 6. The baseline uses the same click sequence without those
postconditions. For a release candidate that does not include FastPath
postconditions, use the same unguarded workload on both builds.

Time from ChatGPT tool-call submission until receipt of the tool result. Use
the tool client's measured duration or a monotonic clock bracketing the
actual ChatGPT MCP dispatch. Keep ≥50 attempts per build and
interleave the builds where possible, with both AB and BA order represented.
Record each attempt, including failures. Mark `verified` only when the tool
confirms all six steps and the expected final page. Use `failed`,
`timed_out`, or `outcome_unknown` otherwise. Inspect `batch_status` and
the staging page without reissuing uncertain input. A later trial must start
on a reset fixture with a new ID.

Outside the timing run, also exercise the owner grant denied/revoked case,
the `#delayed-navigation` button, and a guarded `#no-change` click whose
expected page never appears. Confirm uncertain outcomes do not advance the
guarded sequence, do not trigger replay, and remain observable through
the receipt. Confirm whether the original document navigated before making
another input. Record the exact fixture outcome and review the evidence before
marking each safety field true.

## Score the redacted report

The version 2 report contains source revisions, the pinned Cloudflare Worker revision, the fixture hash, per-attempt sequence numbers and timings,
outcome labels, and reviewed safety booleans. Device IDs, endpoints,
credentials, and raw production tool results belong outside this report. The
example shows the shape with one trial. It is intentionally incomplete.

```json
{
  "schema_version": 2,
  "scope": "chatgpt-cloudflare-windows",
  "environment": "isolated-staging",
  "revisions": {
    "baseline": "<full baseline SHA>",
    "candidate": "<full candidate SHA>"
  },
  "fixture_sha256": "<64 lowercase hex characters>",
  "worker_revision": "<8 lowercase hex characters>",
  "safety_checks": {
    "permission_parity": false,
    "navigation_parity": false,
    "no_replay": false
  },
  "trials": [
    {
      "sequence": 0,
      "variant": "baseline",
      "request_id": "ab-base-0001",
      "elapsed_ms": 5100,
      "outcome": "verified"
    }
  ]
}
```

```powershell
python tools/check_fastpath_e2e.py evidence.json --baseline-sha $baselineSha --candidate-sha $candidateSha --profile fastpath
```

The scorer requires the intended source and Worker revisions, contiguous chronological sequence numbers and unique request IDs, at least 50 attempts per build, and interleaved AB/BA pairs. Grouped baseline-then-candidate runs are rejected. It reports
nearest-rank p50/p95/p99, outcome counts and an error rate, and checks all safety
fields. A non-verified attempt ranks after every verified one. A percentile
that lands on a non-verified attempt is reported as `null`; fast failures
cannot improve the latency result. The `fastpath` profile requires candidate
p95 ≤6,000 ms and a ≥40% p95 reduction. The `release` profile checks the
6,000 ms target.

A green score summarizes submitted evidence. The owner still reviews actual
ChatGPT and Windows observations, the separate paired upgrade/rollback results,
and exact post-merge push CI before approving publication.
