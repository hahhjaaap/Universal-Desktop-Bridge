# Visual frame verification (PR #232)

An opt-in frame guard ties visible pixels, bounds and window identity to an observation ID. It is a snapshot of the physical desktop and cannot prove that an application will acknowledge an input (`src/udb/computer_desktop.py:1523–1573`).

| Question | Evidence and risk |
| --- | --- |
| Replay | A rejected frame precludes guarded input. Partial acceptance after input reaches Windows is uncertain and is not replayed by the batch (`src/udb/computer_desktop.py:574–580,1334–1357`). |
| Isolation | Screenshot mode refuses covered or non-foreground windows. Display capture is separately explicit. Visible pixels are not a private window buffer (`src/udb/computer_desktop.py:788–793,1523–1591`). |
| Input identity | Verifies the same observed window and its captured pixels before pointer input, then performs independent foreground and hit checks. The capture and SendInput are separate operations; they cannot atomically lock the OS surface (`src/udb/computer_desktop.py:882–905,971–1015`). |
| Local override | Owner pause, handoff and grant are checked again in `send`. Guarded actions cannot acquire a different foreground window in order to pass (`src/udb/computer_desktop.py:564–581,817–822`). |
| Untrusted input and limits | Screenshots can contain adversarial text. Only the digest, bounds and requested points act as frame guard evidence. PNGs are capped at 640 KiB (`src/udb/computer_desktop.py:31,1558–1573,1636–1648`). |
