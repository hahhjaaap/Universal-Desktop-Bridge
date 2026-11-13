# Windows startup layout candidate

> **UDB 0.12.0 documentation review (2026-11-13):** This test/candidate record is not proof of the latest Windows release or live acceptance. See [version/status](current-version.md).

The default build remains `onefile` until the candidate's Windows evidence is
reviewed. This change neither installs software on the owner's device nor
changes the public release. Both layouts use the canonical UDB package and the
same owner grants, worker dispatch and local state directory.

```sh
udb build --exe --layout onefile --output dist/startup-onefile
udb build --exe --layout onedir --output dist/startup-onedir
python tools/benchmark_startup.py --onefile dist/startup-onefile/udb.exe --onedir dist/startup-onedir/udb.exe --samples 5 --output reports/startup-layout.json
```

Onedir keeps the bundled interpreter/libraries in `_internal` beside `udb.exe`.
It trades a larger expanded installation for avoiding onefile extraction on
each launch. Copy the complete application directory. Builds require a fresh
output directory to exclude leftover runtime/owner files. Every runtime file is
included in the existing SHA-256 inventory; symlinks/reparse points and owner
state are rejected. No antivirus exclusion or execution-policy setting changes.

The comparison runs on the **same Windows runner and source revision** with
alternating sample order. It records first launch, median and observed p95 for
plain version, build identity, status and doctor, plus actual isolated MCP
initialization/discovery. Each sample is a fresh process; OS and antivirus cache
state are uncontrolled, so the report does not claim a clean OS cold boot or
predict another user's Windows 11 results. Raw process output, paths, tokens
and owner file contents are omitted. All state belongs to a temporary fixture;
the MCP check confirms no host-computer/background grants are enabled.

`.github/workflows/windows-startup-candidate.yml` builds both variants, measures
them, runs copied-directory frozen acceptance with external Python/PATH removed,
then checks actual HTTP install, onefile→onedir update, onedir→onefile rollback,
agent restart, preserved data/preferences, stable Start Menu and failed-update
recovery. It also records fresh-process timings through the actual installed
`udb.cmd` shim before and after the layout switch, including cmd/PowerShell
launcher overhead. The workflow never publishes or deploys a production release.

Promote a new default only after these checks pass, reviewing package size and
representative Windows 11 measurements. Keep the existing onefile release as
the managed rollback path. Startup speed does not establish Cloudflare OAuth,
project-read access, publisher signing or production readiness.
