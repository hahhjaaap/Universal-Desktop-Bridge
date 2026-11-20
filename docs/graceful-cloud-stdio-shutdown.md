# Graceful Cloud LocalProxy shutdown (onefile extraction hygiene)

## Evidence

The owner's frozen Windows UDB v0.13.0 currently uses **onefile**
packaging. Each independent stdio LocalProxy can create a PyInstaller
`_MEI*` extraction folder; on 2026-11-20 a local inspection found
45 such folders, of which five contained DLLs loaded by currently
running processes. The other 40 could be safely removed after
process-module checks. That observation does **not** prove why those
older directories were orphaned.

Previously, `LocalProxy.close()` immediately called
`subprocess.Popen.terminate()` on each still-running stdio proxy.
On Windows this can preempt bootloader / backend teardown and may
leave temporary files. The stdio proxy (`UnifiedProxy.serve`)
already exits on end-of-file, and its nested `StdioChild.close()`
already closes stdin and waits for backend shutdown.

## Change

At authenticated WebSocket teardown, after the executor has finished
in-flight RPCs, `LocalProxy.close()` first closes the subprocess stdin
so `UnifiedProxy.serve` receives EOF. It waits up to **two seconds**
for normal exit; if the worker does not respond, the existing bounded
terminate -> kill fallback remains. Streams and reader threads are
still cleaned up. No user RPC is replayed, and no tool authorization,
Cloudflare pairing, owner state, or process startup behavior changes.

## Verification

Unit tests cover:

- A disposable Python stdio child exits with status 0 after EOF, not
  termination.
- A fake unresponsive subprocess falls back to terminate after the
  bounded EOF grace period.
- A child that ignores terminate still reaches the previous kill path.
- An already-exited child is not terminated or restarted.

These unit tests show the intended lifecycle, but do **not** establish
how many `_MEI*` folders a packaged Windows UDB actually reclaims.
That needs a disposable **Windows onefile** acceptance test with
temporary owner state: sample extraction directory counts before
and after a controlled connect/disconnect for at least ten
independently created proxy subprocesses. Do not clean or restart the
owner's active production processes just to run that measurement.

A future `onedir` release remains a separate build and rollback
decision. This patch is not a substitute for that comparison.
