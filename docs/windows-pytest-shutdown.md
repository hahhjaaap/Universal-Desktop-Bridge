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

## Grouped reproducer on disposable Windows

Run this in PowerShell 7 in a clean source checkout with the development dependencies
and the same user-session conditions as the failing runner. The group names
describe direct test-file imports. The output records transitive modules
actually loaded and separates pytest's return from the native exit code.

```powershell
$env:PYTHONFAULTHANDLER = '1'
$PSNativeCommandUseErrorActionPreference = $false
$tests = @(Get-ChildItem tests -Recurse -Filter 'test_*.py' |
    ForEach-Object { Resolve-Path -LiteralPath $_.FullName -Relative })
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
    $paths = @($group.Value)
    "UDB_NATIVE_GROUP=$($group.Key) files=$($paths.Count)"
    if ($paths.Count -eq 0) { continue }
    python -X faulthandler -c $driver @paths
    $code = $LASTEXITCODE
    '{0} process exit 0x{1:X8} ({2})' -f $group.Key, ([int64]$code -band 0xFFFFFFFFL), $code
    if ($code -ne 0) { $failed = $true }
}
if ($failed) { exit 1 }
```

Repeat the smallest failing group and bisect its test modules. Keep each run
in a fresh Python process. When comparing Python versions, offscreen mode,
or `PYTHONMALLOC=malloc`, vary one parameter at a time. Compare against
`python tools/run_windows_pytest.py results.xml`, which already drains the
global Qt pool, closes and disposes widgets, delivers deferred deletions, and
deletes the test application. Use the recorded process exit code for pass/fail.

The direct Qt cases include the manager UI, quick controls, cloud-first GUI
and common-room GUI fixtures. Audit any isolated failure for surviving
`QApplication`, `QThread`, `QTimer`, or queued callbacks. Check Win32/ctypes
callback lifetime if the Win32-only group reproduces it or the fault trace
points there. A localized teardown fix should wait for a repeatable module or
fixture and evidence that the native exit stops. These diagnostic groups have
not been executed in the current Linux workspace.
