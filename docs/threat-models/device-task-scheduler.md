# Device task scheduler (PR #227)

The principal and device are resolved before scheduling. The resource classifier is static and conservative. It assigns known reads to a read lane, desktop work to one desktop lane, and hosted browser work to its own serialized lane. A launch that may touch multiple resources takes exclusive admission. The physical user and an already-running job remain outside this scheduler's serialization guarantee (`src/udb/remote_task_scheduler.py:53–87,90–146`).

| Question | Evidence and risk |
| --- | --- |
| Replay | Lane wait expiry refuses before execution. Local proxy exchange makes one write attempt; poisoned connections do not start queued work (`src/udb/cloud_agent.py:243–268,310–347`). Distinguish refusal from an unknown in-flight result. |
| Isolation | One active request per serialized resource within a connection. Reads and separate resources can overlap. Shared Windows identity, desktop and owner state remain shared. |
| Input identity | Scheduling conveys a resource class only. Desktop action resolution owns HWND/PID checks (`src/udb/computer_desktop.py:536–581`). |
| Local override | Authorization is checked at dispatch by the local runtime. An active request follows its tool's pause and expiry checks (`src/udb/computer.py:90–132`). |
| Untrusted input and limits | The classifier reads tool names and action fields. Page and window output never enter it. Admission tops out at 10 including the lane queue, with bounded wait (`src/udb/remote_task_scheduler.py:18–20,106–151`). |
