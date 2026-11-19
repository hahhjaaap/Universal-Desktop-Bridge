# Owned browser FastPath DAG (PR #209)

The caller describes a bounded sequence of allowlisted steps, dependencies and exact predicates. The runner binds it to a valid owned session, tab and request ID. The receipt holds a digest and execution counters, with no page payload (`src/udb/browser_batch.py:47–107,139–174`).

| Question | Evidence and risk |
| --- | --- |
| Replay | A receipt is persisted before input. Reusing the request ID with the same plan returns cached or historical state; a different plan is denied. A failed mutation may be unknown (`src/udb/browser_batch.py:146–174,268–339`). A different request ID is a distinct request. |
| Isolation | Proof data is stored in memory per batch, with a fixed tab binding. The session and UI state still belong to the owner and can be observed by a separately authorized client. |
| Input identity | DOM/CDP identity applies. A plan dependency does not pin a native window or freeze the page between steps. |
| Local override | Between each step the service checks cancellation, deadline, current permission and whether the same browser object is still owner-controlled (`src/udb/browser_batch.py:180–215`). |
| Untrusted input and limits | Predicates are typed and match allowlisted observation fields (`src/udb/fastpath.py:16–46,59–138,145–168`). A caller-chosen predicate may use page-controlled evidence. It cannot provide a new instruction or grant. The server enforces 12 steps, 20 seconds, 256 receipts per session and a 65,536-character rendered result per step (`src/udb/browser_batch.py:159–177,279–286`). |
