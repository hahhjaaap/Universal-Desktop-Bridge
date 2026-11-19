# Batch-scoped UIA helper (PR #228)

The desktop batch validates its complete plan before running. When at least two eligible UIA actions need it, one helper lives for the batch and is closed in a finally block. The opt-in persistent mode has a separate longer lifetime. The subprocess runs in the owner's interactive Windows context (`src/udb/computer_desktop.py:1072–1081,1155–1249`).

| Question | Evidence and risk |
| --- | --- |
| Replay | One write attempt per UIA exchange. Timeout, malformed reply or a broken pipe closes the helper and never falls back to re-executing the action (`src/udb/uia_worker.py:139–203`, `src/udb/computer_desktop.py:629–644`). |
| Isolation | Batch helper lifetime is scoped to the Desktop instance and request. The helper's transport serializes exchanges. The OS UIA tree is still the owner's shared desktop. |
| Input identity | Python resolves the window per step, and PowerShell opens a fresh root and checks its PID before evaluating the tree. That is a separate check from pattern invocation (`src/udb/computer_desktop.py:817–862`, `src/udb/computer_uia.ps1:32–55,314–337`). |
| Local override | Dispatch and interactive calls check the owner guard, pause and secure-desktop state. An in-flight UIA provider call does not continuously poll Windows grant state (`src/udb/computer_desktop.py:96–114,604–639,767–785`). |
| Untrusted input and limits | Control names and returned strings are observations. One helper request is capped at 100,000 bytes, one response at 262,144 characters, and each call's timeout at 22 seconds (`src/udb/uia_worker.py:21–22,139–171`). Batch step limit is 12. |
