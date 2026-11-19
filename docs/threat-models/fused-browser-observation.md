# Fused browser action and post-observation (PR #230)

The owned browser combines an action with one bounded post-action snapshot or read. The request binds an owner-managed session and tab. CDP operates on the owned browser and never grants native desktop access (`src/udb/host_service.py:404–442`).

| Question | Evidence and risk |
| --- | --- |
| Replay | Observation failure after input returns the original action evidence and `observation_unavailable`. Skips the read on failed or uncertain input. No action replay (`src/udb/browser_actions.py:84–112`). |
| Isolation | Reads are bound to the result tab or the explicit request tab. The owner may hand off a session and block remote actions. A later same-session call can observe effects left by an earlier authorized client (`src/udb/host_service.py:404–418`). |
| Input identity | HWND/PID are outside the headless browser path. Target tab, page and locator checks belong to browser dispatch (`src/udb/host_browser.py:995–1060`). |
| Local override | Host service checks session control before dispatch. A local owner action during the fused call can race with observation; failed observation must not trigger another action. |
| Untrusted input and limits | The fused read is nested under `observation`. Its page text and DOM labels cannot confer authority. The call uses the 20-second browser service deadline and allowlisted observation values (`src/udb/host_service.py:407–409`, `src/udb/browser_actions.py:55–62`). |
