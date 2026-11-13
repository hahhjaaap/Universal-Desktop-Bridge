# System-level simulation and Windows browser fixture reliability

> **UDB 0.12.0 documentation review (2026-11-13):** This test/candidate record is not proof of the latest Windows release or live acceptance. See [version/status](current-version.md).

UDB already runs a full pytest matrix on Windows/Linux, Python 3.11/3.12,
plus native Windows browser, EXE/package and installer rollback checks. This
addition makes the *scope and gaps* explicit rather than claiming every possible
hardware/network state was simulated.

## CI simulation coverage

`tools/report_system_simulation.py` reads the existing JUnit XML, produces
`udb-simulation.json` with aggregate pass/fail/skip counts and groups tests
across:

- MCP/stdio and recovery;
- Owner permissions and protected resources;
- Files, document conversion and uploads;
- Browser, DOM, CDP and desktop;
- Jobs, host background tasks and termination;
- Packaging and installation;
- Native manager and UI;
- Fault injection, error propagation and no-retry.

A test may contribute to multiple groups. Counts are **not code coverage**,
and categories do not imply every scenario in the domain is tested.
The report deliberately excludes test parameters, tool outputs and host secrets.
GitHub CI reports are available as temporary artifacts.

## Windows browser fixture correction

The disposable host-acceptance worker previously gave **two sequential CDP
setup calls one shared 10-second wall-clock budget**. A Windows runner failed
while establishing `Page.getFrameTree` and did not create the expected
`fixture-ready.json`. This is consistent with delayed responses on an
oversubscribed test runner; it is not proof of a production browser defect.

The QA-only setup now has a **30-second wall-clock budget** and individual
20-second calls, with no automatic retry of an uncertain command, including
`Page.setDocumentContent`. It always restores the browser's prior action
deadline after setup. Production browser limits, permissions and networking
are unchanged. Unit simulation covers successful setup, failures at both
stages, budget restoration and session identity.

An acceptance pass establishes that the fixture worked in that CI environment;
a later failure still needs its actual logs investigated.

## Outside simulation

Physical input devices, Windows Sandbox guest startup, two physical
Windows computers using different Wi-Fi networks, real-world tunnel outages,
antivirus performance and production CPU/RAM require separate owner-authorized
hardware tests. The experimental Multi-PC router remains an independent
draft PR and is not part of the released Windows installer.
