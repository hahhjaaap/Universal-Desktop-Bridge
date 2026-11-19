# Windows pytest shutdown investigation

## Evidence

- [WS1 #212](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/212)
  recorded a successful pytest summary followed by `0xC0000409`. A direct
  interpreter invocation completed on a subsequent run.
- [WS2 #213](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/213)
  recorded `0xC0000409` on Windows Python 3.12.16 after all tests completed.
  Windows Error Reporting named `ucrtbase.dll`. A run with the offscreen
  platform and fault handling produced `0xC0000005`. A 3.11.18 run exited 0.
- [WS3 #214](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/214)
  reported intermittent post-summary failure followed by a clean 3.11 run
  with the allocator and fault-handler options enabled.
- [WS4 #215](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/215)
  recorded `0xC0000005` with `pyside6.abi3.dll` named by Windows Event Log. A
  later isolated 3.11.18 run passed with process-local Qt and Python settings.
- Current `main` at `108e609` completed the Windows [3.11 job](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44339743653/job/134928499291)
  and [3.12 job](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44339743653/job/134928500016).
  Each ran 2,227 tests successfully, skipped 16, emitted `UDB_PYTEST_RETURN=0`
  and `UDB_QT_TEST_CLEANUP=completed`, and passed the process-level CI step.

The historical reports rule out a pytest assertion failure as the sole
explanation for those particular post-summary exits. The clean jobs show
that the current managed runner can finish on both Python versions. Neither
observation identifies a triggering test or attributes the crash to a
specific PySide6, Shiboken6, pywin32, or CRT object. Offscreen mode alone did
not prevent the historical failures. No new runtime fix is proposed yet.

## Hosted Windows Python 3.12 reproduction

[The raw full suite](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44468408799/job/135371659260)
passed 2,253 tests and 29 subtests, skipped 16, and printed
`UDB_PYTEST_RETURN=0`. Python then emitted an access violation without a
Python frame and exited `0xC0000005` (`-1073741819`). The log recorded a live
application and loaded Qt, Shiboken and Win32 modules before the process exit.
The checkout combined `75ae520` with `main` at `7f8d9f3`.

| Direct test-file group | Result | Native modules at pytest return |
| --- | --- | --- |
| [Qt](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44468408799/job/135371658886) | 147 passed, process exit 0 | PySide6 and Shiboken, live application |
| [Win32](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44468408799/job/135371658984) | 140 passed, process exit 0 | pywin32, no Qt application |
| [Neither marker](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44468408799/job/135371658953) | 1,966 passed, 16 skipped, 29 subtests passed, process exit 0 | Transitive pywin32, no Qt application |
| [Both markers](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44468408799/job/135371658692) | No directly matching test files | No Python process started |

The [managed full suite](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44468408796/job/135371737002)
passed on the same checkout with the existing explicit Qt teardown. The Qt
group shows that a live application can survive a clean raw process exit.
The Win32 group can also exit cleanly.

The paired retest combined `90506f7` with the same code on `main` and used
normal pytest collection order within each selection.

| Paired groups | Pytest result | Native process exit |
| --- | --- | --- |
| [Qt and Win32](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44470280975/job/135377774730) | 287 passed | `0x00000000` |
| [Qt and neither marker](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44470280975/job/135377775307) | 2,113 passed, 16 skipped, 29 subtests passed | `0x00000000` |
| [Win32 and neither marker](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44470280975/job/135377775237) | 2,106 passed, 16 skipped, 29 subtests passed | `0x00000000` |

The Qt and Win32 pair exited cleanly with a live application and with
PySide6, Shiboken, pywin32 and `win32ui` loaded. No pair reproduced the
full-suite exit. The experiments establish the native failure and the
observed success of the existing managed runner. They do not isolate a
triggering test or rule out an intermittent failure in a smaller group.

The manager and activity view parent their timers to widgets. The manager
stops its timer on the explicit shutdown path. The quick-controls fixture
waits for the Qt pool after closing the window, and the common-room fixture
uses a shared application. The `WINFUNCTYPE` callbacks inspected in the
sandbox, desktop guest, and virtual pointer are scoped to synchronous
`EnumWindows` calls. These observations do not identify a callback or
active worker surviving interpreter shutdown.

An [initial probe](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44467828309)
exited 2 in two groups because explicitly passed `tests/components` files
bypassed the normal pytest collection exclusion. The corrected groups
below use the regular suite discovery boundaries.

## Grouped reproducer on disposable Windows

Run this in PowerShell 7 in a clean source checkout with the development dependencies
and the same user-session conditions as the failing runner. The group names
describe direct test-file imports. The output records transitive modules
actually loaded and separates pytest's return from the native exit code.
`tests/components` runs through `test_regressions.py` subprocesses,
matching the normal pytest configuration.

```powershell
$env:PYTHONFAULTHANDLER = '1'
$PSNativeCommandUseErrorActionPreference = $false
$tests = @(Get-ChildItem tests -Recurse -Filter 'test_*.py' |
    ForEach-Object { Resolve-Path -LiteralPath $_.FullName -Relative } |
    Where-Object { $_ -notlike '.\tests\components\*' })
$qt = @($tests | Where-Object {
    Select-String -LiteralPath $_ -Quiet -Pattern 'PySide6|shiboken6|QApplication|QThread|QTimer'
})
$win = @($tests | Where-Object {
    Select-String -LiteralPath $_ -Quiet -Pattern '\bwin32[a-z]+\b|pywintypes|WINFUNCTYPE|CFUNCTYPE'
})
$groups = [ordered]@{
    qt_only = @($qt | Where-Object { $_ -notin $win })
    win32_only = @($win | Where-Object { $_ -notin $qt })
    both = @($tests | Where-Object { $_ -in $qt -and $_ -in $win })
    neither = @($tests | Where-Object { $_ -notin $qt -and $_ -notin $win })
    full = $tests
    qt_and_win32 = @($tests | Where-Object { $_ -in $qt -or $_ -in $win })
    qt_and_neither = @($tests | Where-Object { $_ -in $qt -or $_ -notin $win })
    win32_and_neither = @($tests | Where-Object { $_ -in $win -or $_ -notin $qt })
}
$driver = @'
import sys
import pytest

code = int(pytest.main(["-q", *sys.argv[1:]]))
qt_core = sys.modules.get("PySide6.QtCore")
app_live = qt_core is not None and qt_core.QCoreApplication.instance() is not None
loaded = sorted(
    name for name in sys.modules
    if name.startswith(("PySide6", "shiboken6", "win32", "pywintypes"))
)
print(f"UDB_PYTEST_RETURN={code}", flush=True)
print(f"UDB_NATIVE_STATE app={app_live} modules={loaded}", flush=True)
raise SystemExit(code)
'@
$failed = $false
if ($env:UDB_NATIVE_GROUP -and -not $groups.Contains($env:UDB_NATIVE_GROUP)) {
    throw 'Unexpected UDB_NATIVE_GROUP'
}
foreach ($group in $groups.GetEnumerator()) {
    if ($env:UDB_NATIVE_GROUP -and $group.Key -ne $env:UDB_NATIVE_GROUP) { continue }
    if (-not $env:UDB_NATIVE_GROUP -and $group.Key -like '*_and_*') { continue }
    $paths = @($group.Value)
    "UDB_NATIVE_GROUP=$($group.Key) files=$($paths.Count)"
    if ($paths.Count -eq 0) { continue }
    $ignored = @($tests | Where-Object { $_ -notin $paths } |
        ForEach-Object { "--ignore=$_" })
    python -X faulthandler -c $driver @ignored
    $code = $LASTEXITCODE
    '{0} process exit 0x{1:X8} ({2})' -f $group.Key, ([int64]$code -band 0xFFFFFFFFL), $code
    if ($code -ne 0) { $failed = $true }
}
if ($failed) { exit 1 }
```

Set `UDB_NATIVE_GROUP` to a group name to run it alone, including any pair
listed above. The `--ignore` arguments preserve the suite's collection order
among the selected files. Repeat the smallest failing group and bisect its
test modules in fresh Python processes. When comparing Python versions, offscreen mode,
or `PYTHONMALLOC=malloc`, vary one parameter at a time. Compare against
`python tools/run_windows_pytest.py results.xml`, which already drains the
global Qt pool, closes and disposes widgets, delivers deferred deletions, and
deletes the test application. Use the recorded process exit code for pass/fail.

The direct Qt cases include the manager UI, quick controls, cloud-first GUI
and common-room GUI fixtures. Audit any isolated failure for surviving
`QApplication`, `QThread`, `QTimer`, or queued callbacks. Check Win32/ctypes
callback lifetime if the Win32-only group reproduces it or the fault trace
points there. A localized teardown fix should wait for a repeatable module or
fixture and evidence that the native exit stops.

## WS15 current baseline

On `6b46d8322b93b56c8ab26a0b49af24d1f51f6880`, the hosted [Windows Python
3.12 job](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44498559785/job/135479628686)
printed `2295 passed, 18 skipped`, `UDB_PYTEST_RETURN=0`, and
`UDB_QT_TEST_CLEANUP=completed`. GitHub recorded the regression step as
successful. The separate `Check native Windows browser and utility APIs`
step failed with `Owned host operation failed; inspect status before retrying`
and process exit 1. The job failed, but this failure is distinct from the
interpreter exit failure in #238.

The shared application in `tests/test_cloud_first_gui.py:43` and
`tests/test_common_room_gui.py:21` intentionally persists across tests.
The quick-controls fixture drains the global pool after closing its window
(`tests/test_quick_controls.py:21–46`). Manager and activity timers are widget
children (`src/udb/manager.py:212`, `src/udb/activity_gui.py:63`), and the
manager's explicit quit calls `timer.stop()` (`src/udb/manager.py:1497–1510`).
These lifetimes motivate measuring global-pool drain separately from widget
and application disposal. The clean grouped runs in #238 do not identify a
particular fixture or callback as the cause.

The initial diagnostic compared raw full suites with pool drain only. On
[Windows 3.12 with pool drain only](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44508026972/job/135504634209),
pytest reported 2,295 passes, 18 skips, 29 passing subtests and return 0.
The log recorded a live QApplication and a completed pool drain, followed by
an access violation without a Python frame. The native process exited
`0xC0000005` (`-1073741819`). Successful drain alone does not prevent the crash.

An earlier [raw Windows Python 3.11 full suite](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44508026972/job/135504634290)
also returned 0 from pytest, then exited `0xC0000005`. All four later
[raw Windows 3.12 groups](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44510278304)
exited 0. The groups were Qt-only, without direct Qt tests, without direct
Win32 tests and without `test_manager_ui.py`. The group without direct Win32
tests still loaded pywin32 transitively. A clean group run does not establish
an individual triggering fixture for the full suite.

The preceding diagnostic varied only the final explicit deletion of
`QApplication` on Windows Python 3.11 and 3.12. Both arms use the same normal
teardown to drain the pool, close widgets, process deferred deletions and quit
the application. All four [jobs](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/runs/44547192684)
exited 0 with 2,307 passing tests each. The two arms reached their intended
application states. These clean runs did not isolate a cause.

The next comparison runs the full suite without the managed teardown in Python
3.11 and 3.12. Two more Python 3.11 jobs exclude just `test_manager_ui.py` or
just `test_quick_controls.py`. Each job records whether the Qt application is
still active, whether pywin32 is loaded, the number of remaining Python threads,
and the native process exit. Following
a native abort, the isolated hosted job looks for Application Error Event 1000
for the matching Python PID and prints the module name, exception code and
offset when present. No dump, path or settings change is needed.

A faulting module can identify where Windows observed the crash. It cannot
establish which fixture created the invalid state. Keep the managed runner
until the cause is confirmed and three consecutive raw runs complete on each
Windows matrix member without the workaround.
