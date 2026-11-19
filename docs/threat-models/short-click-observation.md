# Short and terminal click observation (PRs #233 and #243)

Caller opt-in can shorten the click navigation observation window when accompanied by a post-action read. The batch path admits this option only on its final click and retains the batch receipt. This trades additional observation time for lower latency with bounded evidence (`src/udb/browser_actions.py:65–81`, `src/udb/browser_batch.py:67–94,139–177`).

| Question | Evidence and risk |
| --- | --- |
| Replay | The action is already issued when the navigation observer times out. The click result declares `replay_safe=false`; the browser batch uses a durable request receipt (`src/udb/host_browser.py:691–708,1049–1060`, `src/udb/browser_batch.py:146–174`). |
| Isolation | The fused observation remains in the owned tab; a final step cannot validate any later mutation in the same batch. A separate authorized call sees current tab state. |
| Input identity | CDP uses logical tab/frame and locator identity rather than Win32 handles. Navigation can change between observation and a later separate call. |
| Local override | Batch verifies background access, session ownership and owner handoff between steps. It cannot interrupt an already-issued CDP click (`src/udb/browser_batch.py:189–215`). |
| Untrusted input and limits | Page text is data. The server limits the observation window to 100–1,000 ms and labels short-window uncertain navigation. A fresh observation is required before a later write; no navigation observed during the window is limited evidence (`src/udb/browser_actions.py:65–81`, `src/udb/host_browser.py:690–708`). |
