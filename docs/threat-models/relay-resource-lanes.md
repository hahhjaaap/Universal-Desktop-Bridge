# Scheduler-capable relay lanes (PR #231)

The Durable Object correlates pending calls with an authenticated device socket. Opted-in agents can schedule known traffic in independent lanes. Registry identity and Windows grants are separate from lane hints (`cloudflare/src/index.js:19–35,325–351`, `src/udb/cloud_agent.py:297–344`).

| Question | Evidence and risk |
| --- | --- |
| Replay | Deadline, partial delivery and socket loss yield an unknown outcome. The Durable Object discards matching reservations and closes the failed socket without replay (`cloudflare/src/index.js:356–430`). |
| Isolation | The reply must match both its socket and request ID. The desktop lane shares a serialized proxy. The owned browser and desktop lanes are not separate users, and browsers or approved jobs can still share local artifacts. |
| Input identity | The relay does not resolve handles. Windows desktop or browser runtime must verify the target for each dispatched action. |
| Local override | Agent admission may finish before local authorization runs. Runtime checks still gate input; a request already in flight may finish (`src/udb/cloud_agent.py:607–623`, `src/udb/computer.py:90–132`). |
| Untrusted input and limits | The capability hint comes from the device connection, after bearer authentication. The server bounds traffic to 10 outstanding RPCs, 25 seconds per dispatch, and one MiB per reply (`cloudflare/src/index.js:19,35,365–392`). Page and window text cannot choose the socket or reservation. |
