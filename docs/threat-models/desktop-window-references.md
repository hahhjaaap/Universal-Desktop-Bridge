# Verified desktop window references (PR #229)

A batch may bind a later action to an earlier unique observation with an exact PID, class and title. HWNDs and titles can change while Windows is processing a call. A visible target, a prevalidated plan and a resolved handle establish the expected target at observation and step resolution (`src/udb/computer_desktop.py:161–220,1193–1217,1288–1305`).

| Question | Evidence and risk |
| --- | --- |
| Replay | Stops or skips on missing observations; failed verification or exception after input begins can report an unknown outcome. Windows batch has no durable receipt or automatic retry (`src/udb/computer_desktop.py:1280–1357`). |
| Isolation | Observation IDs are instance-local and referenced only by the batch's earlier steps. Desktop requests share a physical session. Mutations can change what a later request observes. |
| Input identity | Step resolution rechecks HWND/PID/class and exact title where recorded. The final physical send checks the foreground handle, grant and pause; it does not repeat full identity verification (`src/udb/computer_desktop.py:536–581`). Medium severity. Native handle reuse and its timing remain unverified. |
| Local override | Local grant guard remains bound to the grant that created the Desktop instance. A step or guarded send refuses after revocation or expiry becomes visible (`src/udb/computer.py:124–133`, `src/udb/computer_desktop.py:537–569,774–785`). |
| Untrusted input and limits | Titles and UI attributes are observations, potentially chosen by another application. Predicates use explicit allowlisted fields and prior steps. Twelve steps, 60-second window references and 64 refreshed observations bound the plan (`src/udb/computer_desktop.py:199–211,1072–1153`). No independent aggregate deadline is evident in the desktop batch runner. |
