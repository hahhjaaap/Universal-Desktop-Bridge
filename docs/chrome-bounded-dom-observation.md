# Chrome read observation: bounded visibility scan

## Source-level bottleneck

The UDB-owned Chrome `read` action returns at most **120 visible
interactive elements** and whether more were present. Previously its
page-injected script selected at most 10,000 candidate elements and
called `getComputedStyle` and `getBoundingClientRect` on **every**
candidate with `all.filter(visible)`. These operations can trigger
expensive browser style/layout work on dense applications.

The result never included elements after the first 120, but the
script still paid the visibility-test cost for them.

## Improvement

The script now iterates until the 121st visible element. This is enough
to return the same first 120 controls and the same
`elements_truncated=true` value. It stops asking Chrome to compute the
visibility of later candidates.

An all-visible page with 10,000 matches therefore reduces visibility
checks from **10,000 to 121** (98.79% fewer). On sparse or all-hidden
pages it may still check the entire candidate list. The underlying
shadow-root traversal, maximum candidate count, secret-control redaction,
URL sanitization, page text extraction, and returned fields stay the
same. The `snapshot` command still counts all visible controls because
its output contract includes an exact `count`.

This is a structural reduction in DOM/style work, **not** proof that
wall-clock latency decreases by 98.79%. The rest of page layout,
shadow traversal, CDP transport and server round trips remain.

## Validation

A synthetic Node.js DOM fixture (no browser/profile/network access)
runs both the old and new scripts on 0, 120, 121, 5,000 and 10,000
elements, including hidden nodes and a secret input. It checks exact
JSON output equivalence, preserved redaction and the number of
visibility calculations. The existing complete test suite and security
CI remain mandatory.

Before claiming measurable Chrome speed improvement, benchmark the
same isolated local fixture in **UDB-owned Chrome** 30+ times per
variant: p50/p95 `read` wall time, renderer CPU utilization, CDP
bytes, and correctness on Shadow DOM and pages with dynamic content.
Do not attach to the owner's personal Chrome session, and do not
enable background grants for benchmarking without owner authorization.
