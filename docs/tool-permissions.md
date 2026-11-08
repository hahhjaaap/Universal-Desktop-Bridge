# UDB public tool permissions

- UDB version: 0.11.0
- Public tools: **59**
- Core backend tools before consolidation: 36
- Companion backend tools before consolidation: 31
- Unique backend tools before consolidation: 67

New connections receive only the six explicitly reviewed read tools. All other tools require a separate scope and explicit device/user grant. Windows-side permissions remain authoritative.

| Tool | Scope | Risk | Backend | Local gate |
|---|---|---|---|---|
| bridge_status | udb:read | low | core | registered_project_read_permissions |
| list_projects | udb:read | low | core | registered_project_read_permissions |
| list_files | udb:read | low | core | registered_project_read_permissions |
| read_file | udb:read | medium | core | registered_project_read_permissions |
| check_python_syntax | udb:read | low | core | registered_project_read_permissions |
| propose_file_write | udb:write | high | core | registered_project_write_permissions_and_review |
| propose_sandbox_job | udb:sandbox | high | core | sandbox_owner_grant_or_local_approval |
| propose_media_download | udb:download | high | core | local_download_review_and_https_allowlist |
| get_request_status | udb:jobs | low | core | owner_job_permissions |
| get_job_status | udb:jobs | low | core | owner_job_permissions |
| list_jobs | udb:jobs | low | core | owner_job_permissions |
| propose_desktop_session | udb:sandbox | high | core | sandbox_owner_grant_or_local_approval |
| desktop_status | udb:observe | medium | core | local_observation_permissions |
| desktop_screenshot | udb:observe | high | core | local_observation_permissions |
| desktop_action | udb:sandbox | critical | core | sandbox_owner_grant_or_local_approval |
| desktop_snapshot | udb:observe | high | core | local_observation_permissions |
| desktop_wait_for | udb:observe | medium | core | local_observation_permissions |
| desktop_element_action | udb:sandbox | critical | core | sandbox_owner_grant_or_local_approval |
| desktop_stop | udb:sandbox | high | core | sandbox_owner_grant_or_local_approval |
| search_files | udb:read | low | core | registered_project_read_permissions |
| desktop_app | udb:sandbox | high | core | sandbox_owner_grant_or_local_approval |
| desktop_batch | udb:sandbox | critical | core | sandbox_owner_grant_or_local_approval |
| host_status | udb:observe | medium | core | local_observation_permissions |
| host_start_session | udb:host | high | core | separate_owned_host_session_policy |
| host_browser | udb:host | critical | core | separate_owned_host_session_policy |
| host_workspace | udb:host | high | core | separate_owned_host_session_policy |
| host_screenshot | udb:observe | high | core | local_observation_permissions |
| host_close_session | udb:host | high | core | separate_owned_host_session_policy |
| computer_status | udb:observe | medium | core | local_observation_permissions |
| computer_files | udb:computer | critical | core | attended_current_user_computer_grant |
| computer_process | udb:computer | critical | core | attended_current_user_computer_grant |
| computer_desktop | udb:computer | critical | core | attended_current_user_computer_grant |
| terminal_start | udb:execute | critical | companion | attended_computer_access_and_project_root |
| terminal_read | udb:execute | low | companion | attended_computer_access_and_project_root |
| terminal_stop | udb:execute | high | companion | attended_computer_access_and_project_root |
| file_list | udb:read | low | companion | attended_computer_access_and_project_root |
| file_read | udb:read | medium | companion | attended_computer_access_and_project_root |
| file_write | udb:write | high | companion | attended_computer_access_and_project_root |
| file_replace | udb:write | high | companion | attended_computer_access_and_project_root |
| file_search | udb:read | low | companion | attended_computer_access_and_project_root |
| file_stat | udb:read | low | companion | attended_computer_access_and_project_root |
| file_mkdir | udb:write | medium | companion | attended_computer_access_and_project_root |
| file_read_lines | udb:read | low | companion | attended_computer_access_and_project_root |
| terminal_list | udb:execute | low | companion | attended_computer_access_and_project_root |
| terminal_interact | udb:execute | critical | companion | attended_computer_access_and_project_root |
| search_start | udb:jobs | low | companion | attended_computer_access_and_project_root |
| search_read | udb:jobs | low | companion | attended_computer_access_and_project_root |
| search_stop | udb:jobs | low | companion | attended_computer_access_and_project_root |
| file_read_chunk | udb:read | low | companion | attended_computer_access_and_project_root |
| file_upload | udb:write | high | companion | attended_computer_access_and_project_root |
| file_operation | udb:write | high | companion | attended_computer_access_and_project_root |
| system_process_list | udb:observe | medium | companion | attended_computer_access_and_project_root |
| system_process_terminate | udb:computer | critical | companion | attended_computer_access_and_project_root |
| work_recovery | udb:jobs | high | companion | attended_computer_access_and_project_root |
| virtual_pointer | udb:computer | high | companion | attended_computer_access_and_project_root |
| spreadsheet | udb:write | high | companion | attended_computer_access_and_project_root |
| word_document | udb:write | high | companion | attended_computer_access_and_project_root |
| pdf_document | udb:write | high | companion | attended_computer_access_and_project_root |
| file_transfer | udb:write | high | companion | attended_computer_access_and_project_root |
