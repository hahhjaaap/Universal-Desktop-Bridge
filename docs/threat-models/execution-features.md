# WS14 execution feature audit

The source baseline is `6b46d8322b93b56c8ab26a0b49af24d1f51f6880`. This is a source review with an isolated dependency-injected contract test. No real desktop input, browser session, relay, Windows grant, or owner configuration was exercised.

| Severity | Finding | Evidence |
| --- | --- | --- |
| Medium | Desktop identity is checked at step resolution. The final physical input call only rechecks foreground handle, owner access and pause. Full HWND/PID/class/title verification is missing at that boundary. | `src/udb/computer_desktop.py:536–581,817–841,907–919`. See the [window model](desktop-window-references.md). |
| Medium | Relay lanes serialize resources within one connection. They do not provide separate OS accounts or separate physical desktops for each client. | `cloudflare/src/index.js:325–344,356–383`, `src/udb/cloud_agent.py:297–338`, `src/udb/remote_task_scheduler.py:80–103,106–151`. Same-owner clients share the local resources by design. |
| Low | Short click observation cannot establish the absence of future navigation. | `src/udb/browser_actions.py:65–81`, `src/udb/host_browser.py:691–708`. The result carries the limitation. |
| Low | Desktop input and browser actions already in flight may complete after a local pause, handoff or expiry. | `src/udb/computer_desktop.py:564–581,625–680`, `src/udb/browser_batch.py:189–215,253–267`. Between-step checks narrow the window. |
| Low | UI and page content may influence client decisions if a client fails to separate data from authorization. | `src/udb/browser_actions.py:90–112`, `src/udb/fastpath.py:145–168`, `src/udb/computer_desktop.py:464–491`. See [ChatGPT UI text](desktop-chatgpt-ui.md). |

The individual models cover the requester, device and resource boundary, replay contract, authorization rechecks, untrusted observations and enforcement limits. No automated repro of native HWND reuse or concurrent Cloudflare Durable Objects was attempted.
