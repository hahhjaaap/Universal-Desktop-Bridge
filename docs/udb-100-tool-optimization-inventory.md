# Kiểm kê và đề xuất hoàn tất 100 tối ưu từng công cụ UDB

**Ngày kiểm kê:** 2026-11-15. **Nguồn catalog:** `cloudflare/src/fleet-tool-catalog.json` (blob SHA `964100ee09a339efdd97e68af2b18cd88ccbed25`, 40 public tools trên `main`). **Phạm vi:** repository `hahhjaaap/Universal-Desktop-Bridge`. **Trạng thái:** BẢN KẾ HOẠCH ĐỀ XUẤT, không phải một đợt benchmark hay chứng nhận đã triển khai.

## 1. Quy tắc xác nhận hoàn thành

- **Code merged**: tính cho danh sách 1–30 nếu có PR được merge và mô tả rõ công cụ; chưa mặc nhiên khẳng định bản cài Windows/Cloudflare đã nâng cấp.
- **Có tối ưu lịch sử**: khác với 100-step ledger; một công cụ có thể đã sửa hiệu năng ở PR khác nhưng chưa có benchmark mới. Không được gọi là “chưa hề tối ưu”.
- **Chưa có chứng cứ**: không đồng nghĩa công cụ chưa hoạt động hoặc chưa tối ưu. Cần benchmark baseline + tests trước khi sửa.
- **31–40**: người dùng xác nhận mốc hiện tại là bước 40, nhưng chưa tìm thấy bảng từng bước, PR và kết quả đo đủ tin cậy để lập mapping. **Giữ 10 số này là “chờ đối chiếu”; không phát minh rằng một PR khác đã làm xong chúng.**
- **41–100**: là phương án phân bổ 60 tối ưu **đề xuất** để lấp các khoảng trống của 40 public tools và các backend. Trước khi thực hiện từng bước phải đối chiếu ledger 31–40 để chống làm lại; có thể đổi thứ tự hoặc loại bỏ mục đã hoàn tất.

## 2. Bằng chứng đã merge

| Số bước | Công cụ/chức năng | Bằng chứng |
| --- | --- | --- |
| 1–2 | Cloudflare fleet `list_devices` (không thuộc 40 public tools local) | [#184](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/184) |
| 3–4 | `bridge_status` | [#184](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/184) |
| 5–6 | `list_projects` | [#184](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/184) |
| 7–8 | `host_status` | [#184](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/184) |
| 9–10 | `computer_status` | [#184](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/184) |
| 11–12 | `list_files` | [#188](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/188) |
| 13–14 | `read_file` + batch alias `read_files` | [#188](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/188) |
| 15–16 | `search_files` | [#188](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/188) |
| 17–18 | `check_python_syntax` | [#188](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/188) |
| 19–20 | `project_files` wrapper + native file list/stat/read_lines | [#188](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/188) |
| 21–22 | `propose_file_write` + text-edit alias | [#189](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/189) |
| 23–24 | `file_write` | [#189](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/189) |
| 25–26 | `file_replace` | [#189](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/189) |
| 27 | `file_mkdir` | [#189](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/189) |
| 28–29 | `file_transfer` and native copy/move | [#189](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/189) |
| 30 | `computer_files` | [#189](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/189) |

Các hiệu năng đã được cải tiến **ngoài 100-step ledger**:
- [#32](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/32): browser CDP, Shadow DOM, event queues và navigation wait.
- [#37](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/37) / [#38](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/38): MCP startup read, host inbox idle và RPC waiter/schema cache.
- [#39](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/39): manager finished-job UI refresh.
- [#139](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/139): owner-scoped `search_files` prefilter (benchmark fixture cũ; không ngoại suy sang mọi workload).
- [#173](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/173): memory build hashing, GUI sandbox hint cache, bounded activity metadata.
- [#176](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/176): đơn giản hóa MCP dispatch path, hashing và admission.

**[#192](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/192) vẫn là draft độc lập** về host mailbox; **không tính cho 31–40**.

## 3. Ma trận kiểm kê đầy đủ 40 công cụ public

Cột “Chưa thấy PR chuyên biệt” chỉ mô tả bằng chứng kiểm kê, **không phải kết luận chưa được tối ưu**. Một public tool có thể có nhiều action/native handlers.

| # | Tool | Trạng thái có bằng chứng | Nguồn | Đề xuất 41–100 |
| ---: | --- | --- | --- | --- |
| 1 | `bridge_status` | Đã có tối ưu trong roadmap 1–30 | 3–4, #184 | Theo dõi benchmark hồi quy |
| 2 | `list_projects` | Đã có tối ưu trong roadmap 1–30 | 5–6, #184 | Theo dõi benchmark hồi quy |
| 3 | `list_files` | Đã có tối ưu trong roadmap 1–30 | 11–12, #188 | Theo dõi benchmark hồi quy |
| 4 | `read_file` | Đã có tối ưu trong roadmap 1–30 | 13–14, #188 | Theo dõi benchmark hồi quy |
| 5 | `check_python_syntax` | Đã có tối ưu trong roadmap 1–30 | 17–18, #188 | Theo dõi benchmark hồi quy |
| 6 | `propose_file_write` | Đã có tối ưu trong roadmap 1–30 | 21–22, #189 | Theo dõi benchmark hồi quy |
| 7 | `propose_sandbox_job` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 41–42 |
| 8 | `propose_media_download` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 91 |
| 9 | `get_request_status` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 43 |
| 10 | `get_job_status` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 44 |
| 11 | `list_jobs` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 45 |
| 12 | `propose_desktop_session` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 46 |
| 13 | `search_files` | Đã có tối ưu trong roadmap 1–30 | 15–16, #188 | Theo dõi benchmark hồi quy |
| 14 | `host_status` | Đã có tối ưu trong roadmap 1–30 | 7–8, #184 | Theo dõi benchmark hồi quy |
| 15 | `host_start_session` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 61 |
| 16 | `host_workspace` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 62 |
| 17 | `host_close_session` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 63 |
| 18 | `computer_status` | Đã có tối ưu trong roadmap 1–30 | 9–10, #184 | Theo dõi benchmark hồi quy |
| 19 | `computer_files` | Đã có tối ưu trong roadmap 1–30 | 30, #189 | Theo dõi benchmark hồi quy |
| 20 | `computer_process` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 51–54 |
| 21 | `computer_desktop` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 55–60 |
| 22 | `file_write` | Đã có tối ưu trong roadmap 1–30 | 23–24, #189 | Theo dõi benchmark hồi quy |
| 23 | `file_replace` | Đã có tối ưu trong roadmap 1–30 | 25–26, #189 | Theo dõi benchmark hồi quy |
| 24 | `file_search` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 79 |
| 25 | `file_mkdir` | Đã có tối ưu trong roadmap 1–30 | 27, #189 | Theo dõi benchmark hồi quy |
| 26 | `file_read_chunk` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 81 |
| 27 | `file_upload` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 82–84 |
| 28 | `file_operation` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 85 |
| 29 | `work_recovery` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 80 |
| 30 | `virtual_pointer` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 70 |
| 31 | `spreadsheet` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 86–88 |
| 32 | `word_document` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 89 |
| 33 | `pdf_document` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 90 |
| 34 | `file_transfer` | Đã có tối ưu trong roadmap 1–30 | 28–29, #189 | Theo dõi benchmark hồi quy |
| 35 | `terminal` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 71–75 |
| 36 | `sandbox_desktop` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 47–50 |
| 37 | `search` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 76–78 |
| 38 | `system_process` | Chưa thấy PR tối ưu chuyên biệt trong ledger 1–30 | Cần baseline theo công cụ | 92–93 |
| 39 | `project_files` | Đã có tối ưu trong roadmap 1–30 | 19–20, #188 | Theo dõi benchmark hồi quy |
| 40 | `browser` | Có tối ưu lịch sử; chưa xác minh theo 100 bước | #32: tối ưu CDP/DOM/wait_for; chưa phải bước 1–30 | 64–69 |

**Tổng hợp:** 15/40 public tools có bằng chứng gắn với 1–30; 25/40 cần rà soát ngoài ledger 1–30, trong đó `browser` có bằng chứng tối ưu lịch sử #32. `list_devices` thuộc lớp Cloudflare fleet, được ghi riêng.

## 4. Kế hoạch ưu tiên 6 đợt, bước 41–100

| Đợt | Phạm vi | Điều kiện an toàn |
| --- | --- | --- |
| 41–50 | Sandbox, approvals và job trạng thái | Tối ưu read/poll/trì hoãn tạo job; giữ approval, resource caps và guest isolation |
| 51–60 | Windows computer process + UIA | Chỉ chạy trên máy/dev sandbox được chủ máy cho phép; giữ HWND/PID freshness và local pause |
| 61–70 | Host sessions, browser và con trỏ AI | Dựa benchmark thực tế; không chạm phiên browser hay con trỏ người dùng |
| 71–80 | Terminal, background search và recovery | Bounded streaming/cursor; ngăn command replay và quyền vượt scope |
| 81–90 | File upload/operation và tài liệu | Source hash, create-only, rollback; XLSX/DOCX/PDF fixture chính xác |
| 91–100 | Media, system process, fleet/MCP và phát hành | Không cache quyền, bảo đảm device scoping và installer rollback |

## 5. Danh sách chi tiết 60 bước đề xuất

Mỗi bước phải có: (1) benchmark trước/sau trên fixture có thể tái tạo; (2) một thay đổi rõ ràng ở đúng tool/action; (3) regression positive/negative; (4) kiểm tra CPU/RSS/IO/p50/p95 phù hợp; (5) không giảm quyền, không replay, không xóa dữ liệu thực.

| Bước | Công cụ/action | Thay đổi dự kiến | Tiêu chí bắt buộc |
| ---: | --- | --- | --- |
| 41 | `propose_sandbox_job` | Kiểm tra sớm ngôn ngữ, timeout, giới hạn script trước tạo snapshot | Không tạo file/job khi request bị từ chối; quyền local không đổi |
| 42 | `propose_sandbox_job` | Giảm copy snapshot và chi phí chuẩn bị môi trường cho job lặp | So sánh bytes/RSS/startup; không tái dùng snapshot khi quyền hoặc source đổi |
| 43 | `get_request_status` | Tối ưu tra cứu outcome theo request_id với chỉ mục/câu SQL bounded | Kết quả và độ mới giống trước; quyền phê duyệt không cache |
| 44 | `get_job_status` | Đọc log theo offset, giới hạn bytes, bỏ truy vấn thừa | Chống stale cursor và log tăng; không xuất dữ liệu ngoài phạm vi |
| 45 | `list_jobs` | Tối ưu truy vấn 30 job gần nhất và metadata cần thiết | Không tăng phạm vi lịch sử; giải thích tie/order; query count giảm |
| 46 | `propose_desktop_session` | Tiền kiểm task/duration/grant trước snapshot và khởi tạo guest | Không bypass approval, không tự truy cập host; test denied path |
| 47 | `sandbox_desktop status/stop` | Loại bỏ poll không cần thiết; stop luôn khả dụng khi cần dừng an toàn | Độ mới trạng thái và emergency stop; regression revocation |
| 48 | `sandbox_desktop screenshot` | Hạn chế bản copy bitmap/encode và payload lớn | Peak RSS/bytes giảm, ảnh đúng, guest-only, no host fallback |
| 49 | `sandbox_desktop snapshot/wait_for` | Tối ưu poll UIA theo deadline, tránh lặp toàn cây | p95 giảm trên fixture; không mất control hoặc giả success |
| 50 | `sandbox_desktop input/element/batch/app` | Tối ưu chuỗi bước giới hạn, giảm observation trùng | Không replay click/mutation; mọi bước recheck quyền/stop |
| 51 | `computer_process start` | Giảm tiền kiểm/spawn setup dư thừa cho job Win32 đã được cấp quyền | PID/job ownership chính xác, không mở rộng allowlist chương trình |
| 52 | `computer_process read` | Dùng offset/tail bounded cho stdout/stderr lớn | Không quét lại log; hash/offset phù hợp, không làm mất dữ liệu |
| 53 | `computer_process list` | Chỉ trả metadata job sở hữu, query theo trang nếu cần | Không quét tiến trình ngoài phạm vi; stable ordering |
| 54 | `computer_process stop` | Tối ưu cleanup Job Object/stop khi tiến trình đã dừng | Idempotent cleanup, không kill PID không sở hữu |
| 55 | `computer_desktop windows/snapshot` | Tiết kiệm lượt enumerate UIA/desktop không cần thiết | Window identity luôn mới, không cache HWND/quyền lỗi thời |
| 56 | `computer_desktop screenshot` | Giảm bản sao hình và lựa chọn vùng capture | Occlusion/foreground/window identity recheck giữ nguyên |
| 57 | `computer_desktop read_text` | Đọc TextPattern/ValuePattern theo giới hạn và Unicode boundary | Không đọc password field; không cắt surrogate pair |
| 58 | `computer_desktop UIA input` | Giảm postcondition poll khi trạng thái đã đạt | Không bấm/toggle lặp; không giả xác nhận khi không quan sát được |
| 59 | `computer_desktop clipboard` | Giảm copy chuỗi và thao tác đọc/ghi không cần thiết | expected_version CAS, local pause và dữ liệu không tin cậy giữ nguyên |
| 60 | `computer_desktop apps/launch_app/notify` | Tối ưu dựng danh sách app, gọi theo ID quan sát | Whitelist và cooperative input; không khởi chạy đường dẫn tùy ý |
| 61 | `host_start_session` | Tối ưu khởi tạo profile UDB-owned và admission | Không chạm browser người dùng; giữ tài nguyên/giới hạn session |
| 62 | `host_workspace` | Giảm chuyển đổi văn bản và refresh cửa sổ riêng | Đọc/set_text đúng byte, không tự focus hoặc ghi file |
| 63 | `host_close_session` | Tối ưu dọn profile/process, tránh quét nhiều lần | Chỉ close UDB-owned, không nuốt lỗi cleanup gây leak |
| 64 | `browser control/navigation` | Profile p95 CDP navigation/timeout, giảm RPC lặp | Giữ nguyên no-replay, isolated profile và deadline |
| 65 | `browser DOM/selector` | Tiếp tục tối ưu Shadow DOM/MutationObserver khi profile cho thấy bottleneck | Không cache context sau navigation; không sai selector |
| 66 | `browser screenshot` | Giảm full-frame copies và encode payload | Giới hạn ảnh, origin/tab identity, cap RAM |
| 67 | `browser batch/capture cache` | Khử quan sát thừa, giới hạn fps và queue | Không replay mutations; stop/cancel giữa bước đúng |
| 68 | `browser upload/download` | Truyền dữ liệu theo luồng có SHA và size caps | Expected origin, no overwrite, không chạm file ngoài scope |
| 69 | `browser session lifecycle` | Hạn chế warm-start và task process overhead | Khép kín profile/process và credential isolation |
| 70 | `virtual_pointer` | Giảm số lần cập nhật overlay/Win32 messages khi bất động | Không SendInput, không di chuyển con trỏ thật, local pause |
| 71 | `terminal start` | Tối ưu startup ConPTY/PTY trong owner-scoped project | Giới hạn shell/cwd, lệnh không auto-retry |
| 72 | `terminal list` | Query session metadata theo phạm vi, tránh scan output | Không lộ terminal của người dùng khác |
| 73 | `terminal read/wait` | Tail theo cursor, giới hạn output và timeout | Không nhầm prompt heuristic với exit code |
| 74 | `terminal interact/send` | Giảm vòng poll sau send, bảo toàn thứ tự gửi | Không gửi trùng, ngắt và trạng thái unknown minh bạch |
| 75 | `terminal stop` | Dọn subprocess/pipe, handle nhanh khi owner thu hồi quyền | Không kill tiến trình ngoài Job/session sở hữu |
| 76 | `search start` | Tối ưu bộ lọc glob/regex và lập lịch worker | Cap CPU/file count, không dò protected roots |
| 77 | `search read` | Đọc kết quả theo cursor, tránh materialize tất cả hits | Không trùng/mất hit, payload bounded |
| 78 | `search stop` | Cancel/cleanup prompt và chắc chắn hoàn trả resource | Không giữ worker chết, không stop job không sở hữu |
| 79 | `file_search + context` | Tối ưu sinh context quanh matches bằng streaming | Không đổi ngữ nghĩa regex/literal hoặc lộ hidden files |
| 80 | `work_recovery` | Đọc receipt/checkpoint tối thiểu, phân biệt unknown outcome | Không replay side effects; phục hồi output hạn chế |
| 81 | `file_read_chunk` | Bộ nhớ bounded theo chunk 1 MiB, xác thực phiên bản qua nhiều lượt | Source đổi thì fail, giữ giới hạn 16 GiB |
| 82 | `file_upload begin` | Tối ưu preflight size/SHA/quota trước tạo tệp tạm | Create-only, quota, scope và ownership đầy đủ |
| 83 | `file_upload write` | Giảm base64 copies, xác thực offset/part digest | Chunk order, không chồng lấn, không ghi ngoài scope |
| 84 | `file_upload status/commit/abort` | Streaming verify SHA và cleanup an toàn | Không publish sai digest; no overwrite; owned temp cleanup |
| 85 | `file_operation copy/move/read/cancel` | Tối ưu copy tree và job polling theo luồng | No-overwrite, source hash CAS, scoped cancellation |
| 86 | `spreadsheet inspect/read` | Đọc XLSX theo phạm vi sheet/range, không load format không cần | Đúng công thức/cell types, memory bounded |
| 87 | `spreadsheet write/edit` | Gom thay đổi theo lô, ghi tệp atomically | Giữ style/formula, recover/approval/no overwrite |
| 88 | `spreadsheet audit_invoices/export_audit` | Tối ưu đối chiếu hóa đơn và xuất báo cáo XLSX | Khớp số theo test fixture VN, không sửa bảng gốc |
| 89 | `word_document` | Tối ưu DOCX read/replace theo paragraph/run, lưu atomic | Không mất style/hyperlink, theo approval và file cap |
| 90 | `pdf_document` | Tối ưu PDF parse/extract/merge trong page/size budgets | Không mất trang, file được bảo vệ, cancelable job |
| 91 | `propose_media_download` | Tối ưu HLS playlist/segment buffering và retry an toàn | Chỉ allowlisted HTTPS, không overwrite, không đổi approval |
| 92 | `system_process list` | Giảm enumerate process và giữ ID quan sát | Không lộ hoặc thao tác process ngoài scope |
| 93 | `system_process terminate` | Giảm xác minh PID lặp nhưng vẫn chống PID reuse | Chỉ terminate observed allowed target sau consent |
| 94 | `fleet_call routing` | Giảm số lần phân giải device/route giữa ChatGPT và Cloudflare | Exact device_id mỗi call, owner isolation, no cached grant |
| 95 | `fleet_list_computers / list_devices` | Tối ưu lọc offline/unverified và fanout diagnostics | Tiếp nối #184, không lặp lại if_revision; per-call owner verify |
| 96 | `MCP proxy initialize/tools_list` | Profile p95 startup và copy schema, chỉ tối ưu bottleneck mới | Không lặp #37–38; deterministic catalog, no mixed-backend grants |
| 97 | `tool family dispatch` | Giảm chuyển alias/action/arguments khi đã validate | Giữ cùng original grant, không nâng quyền family |
| 98 | `udb setup / doctor --cloud` | Tối ưu health check/connection diagnostic theo deadline | Không gọi ra remote bí mật, không chuyển từ read-only sang mutate |
| 99 | `udb tools + packaged catalog` | Tối ưu catalog load/read trong wheel/EXE | 40 public + native parity, frozen catalog và version chính xác |
| 100 | `udb install/update/rollback` | Profile cold start và update/rollback kiểm chứng | Không xóa owner state; signed identity/manifest và rollback test |

## 6. Quy trình kiểm thử, số đo và bàn giao

1. **Baseline:** `main` ở SHA cố định, fixture test riêng; ghi p50/p95, số lần RPC/I/O, peak RSS và bytes output. Báo cáo ít nhất 20–30 mẫu/lượt cho microbenchmark; warm/cold start riêng. Không đặt ngưỡng speed cứng dùng chung máy.
2. **Sửa hẹp:** mỗi PR chỉ 5–10 bước, tránh đổi public schema hay output mặc định nếu không có migration. Tối ưu trên code đọc/IO, không cache owner consent hoặc path-policy decision.
3. **Regression:** Linux/Windows Python 3.11/3.12, Ruff, catalog parity với Cloudflare, Windows EXE/frozen acceptance, rollback; fixture truy cập bị từ chối, revoke giữa thao tác, symlink/hardlink, timeout, và mutation outcome unknown.
4. **Đối chiếu release:** phân biệt code `main`, installer đang phát hành, EXE đã cài và Cloudflare Worker đang deploy. Không có thiết bị online thì không xác nhận on-device.
5. **Ledger:** ghi ở mỗi bước mã PR, SHA, before/after số đo, CI, trạng thái `proposed / code / tests / merged / shipped`, liên kết rollback.
6. **Khoảng trống:** tìm hoặc dựng lại mapping **31–40** trước khi tuyên bố số bước hoàn thành vượt 40; loại bỏ công việc 41–100 bị trùng bằng chứng có sẵn.

## 7. Những việc tuyệt đối không được làm để cải thiện số đo

Không bỏ authorization hoặc prompt approval; không giữ cache quyền khi owner đã thu hồi; không nới scope browser, Sandbox, đường dẫn, terminal; không tự replay side-effecting calls khi timeout; không bỏ SHA no-overwrite/recovery; không xóa profile/backup trên máy thật; không auto-deploy Cloudflare hoặc thay Windows EXE chỉ vì CI green.


## 8. Bảng tiến độ triển khai 41–50 (PR #195)

- **PR triển khai:** [#195](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/195) — Draft, không được tính là merged/shipped.
- **Bước 41:** code tiền kiểm request `propose_sandbox_job`, regression invalid inputs.
- **Bước 42:** tái sử dụng `Path(parent)` mỗi thư mục và lọc hậu tố nhẹ hơn trong source snapshot; giữ nguyên quyền/caps.
- **Bước 43:** fast path result JSON rỗng cho `get_request_status`.
- **Bước 44:** tránh probe `exists` thừa trước khi đọc bounded job log.
- **Bước 45:** `list_jobs(limit=1..30)` tùy chọn; mặc định trả 30, cập nhật generated Fleet catalog.
- **Bước 46:** `propose_desktop_session` kiểm tra task và duration trước khi dò Sandbox.
- **Bước 47:** guest command tái dùng session row đã xác thực trong cùng lượt, vẫn tái kiểm tra quyền khi chờ.
- **Bước 48:** CRC PNG theo `memoryview` thay vì copy khối IDAT lớn.
- **Bước 49:** internal readiness bỏ đọc `progress.json` dư; public desktop status vẫn đầy đủ.
- **Bước 50:** bảng lock `desktop_control` tạo một lần ở Agent init, vẫn giữ transactional per-session lock và cancel/revocation.
- **Nghiệm thu:** cross-platform CI, Windows EXE và relay validation phải đạt trên cùng SHA; trước đó trạng thái toàn nhóm là **code + tests, chờ merge**.
- **Phạm vi chưa xác minh:** Windows Sandbox trên máy thật và chi phí toàn bộ end-to-end ChatGPT không được chứng minh chỉ bằng CI.
