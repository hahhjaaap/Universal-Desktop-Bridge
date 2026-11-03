# Checklist ghép nối UDB ↔ Cloudflare ↔ ChatGPT (owner-attended)

> **Trạng thái:** hướng dẫn chuẩn bị, **không** phải bằng chứng đã kết nối.
> Mọi thao tác cấp quyền/đăng nhập đều cần chủ máy tự xác nhận.

## 1. Tách ba lớp kết nối

1. **Windows UDB:** đúng bản có Cloud Pair/Cloud Agent; người dùng xác nhận quyền cục bộ.
2. **Cloudflare Relay:** thiết bị đăng ký qua mã mời một lần, agent mở kết nối
   WebSocket outbound trên `/v1/devices/DEVICE_ID/connect`. Đường WebSocket
   không được buộc đăng nhập Cloudflare Access kiểu Worker-wide.
3. **ChatGPT MCP:** Cloudflare Access Managed OAuth bảo vệ **chính xác** URL
   `https://WORKER.workers.dev/v1/devices/DEVICE_ID/mcp`; Worker kiểm
   `ctx.access`, audience và grant thiết bị. Không tạo quyền shell, ghi tệp,
   thao tác GUI hoặc bypass quyền cục bộ.

**Nhầm lẫn thường gặp:** `/health = 200`, nút "Cloud Agent đã bật", một
thiết bị có trong Relay, hoặc ChatGPT báo "Connected" **đều không đủ**
để kết luận thao tác MCP end-to-end thành công.

## 2. Có thể chuẩn bị trước khi chủ máy đăng nhập

- Chạy CI Windows, Ubuntu, Node Cloudflare; chỉ dùng commit đã qua kiểm thử.
- Kiểm tra UDB hiện cài qua `udb.cmd --version` nếu PowerShell không cho
  chạy `udb.ps1`. Không hạ ExecutionPolicy; không tự thay thế bản đang chạy.
- Đặt source/bản build kiểm thử vào thư mục **staging** riêng. Phân biệt
  source trên `main`, artifact từ CI và bản stable đã phát hành.
- Kiểm tra tài khoản Cloudflare có Zero Trust và quyền quản lý Access app.
- Chuẩn bị hostname Worker, thiết bị đích và email đăng nhập của chủ máy
  **trong cấu hình riêng tư**, không đẩy lên repo/issue/chat.
- Không tạo mã mời quá sớm: thời hạn chỉ 600 giây.
- Không tự triển khai Worker, bật Managed OAuth, tạo grant hay bật Cloud Agent
  trên máy khác mà chưa có xác nhận tương ứng.

## 3. Lúc chủ máy có mặt — trình tự tối thiểu

1. Xác nhận cài đúng bản UDB chứa mục **Kết nối → Nhập mã mời Cloud**
   và nút **Bật Cloud Agent**. Bản stable cũ có thể chưa có.
2. Trên Cloudflare Relay **đã triển khai có kiểm soát**, tạo lời mời từ
   `POST /v1/admin/pairings` bằng admin key bí mật trong terminal tin cậy.
   Chỉ nhập admin key tại chỗ. Lời mời gồm device ID và pairing code một lần,
   hạn 10 phút; **không đưa vào lịch sử chat hoặc git**.
3. Trong UDB Manager trên Windows, chọn **Nhập mã mời Cloud** và nhập
   HTTPS Worker origin, device ID, mã mời qua ô bí mật; chủ máy xác nhận.
   Nếu dùng CLI mới, `udb cloud-pair` hỏi thông tin tương đương trong
   terminal trực tiếp. Không đưa mã mời vào tham số dòng lệnh.
4. Sau khi `claim` xác nhận, bấm **Bật Cloud Agent** theo phiên. Kiểm tra
   trạng thái remote của đúng device ID; không đánh đồng với ChatGPT.
5. Trong Cloudflare Zero Trust, tạo **self-hosted Access application giới
   hạn chính xác đường dẫn MCP của thiết bị** và policy chỉ cho danh tính
   chủ máy, sau đó bật **Managed OAuth** trên app. **Không** bật Worker-level
   Access cho toàn bộ Worker hoặc `/connect` WebSocket.
6. Dùng thiết lập riêng tư, không commit: `UDB_AUTH_MODE=cloudflare-access`,
   `UDB_ACCESS_AUD` bằng audience thật của Access app,
   `UDB_ACCESS_TEAM_DOMAIN=https://TEN_TEAM.cloudflareaccess.com` để xác minh
   chữ ký JWT Access nếu `ctx.access` không có danh tính, và
   `UDB_DEVICE_GRANTS` cấp đúng chủ máy/thiết bị. Chỉ cho phép công cụ
   read-only `bridge_status`, `list_projects`. Admin RPC vẫn tắt.
7. Chạy kiểm tra **không dùng token** (sau khi Worker có phiên bản mã mới
   và Managed OAuth đã thực sự bảo vệ MCP path):
   
   ```powershell
   python tools/check_cloudflare_deployment.py --relay https://WORKER.workers.dev --device-id DEVICE_ID --auth-mode cloudflare-access
   ```

   Kết quả đúng xác nhận HTTP health, challenge OAuth và metadata Cloudflare
   qua các phản hồi không kèm token; **không** chứng minh bằng mật mã rằng edge
   đang thực thi đúng policy và **không** xác nhận đã đăng nhập.
8. Trong ChatGPT, thêm MCP server riêng bằng **chính xác URL MCP**,
   bắt đầu đăng nhập Cloudflare và hoàn thành consent do chủ máy thực hiện.
   Kiểm tra danh sách công cụ read-only và gọi `bridge_status` trên đúng máy.
9. Kiểm thử trường hợp bị từ chối: thiếu đăng nhập, danh tính khác, audience
   khác, device khác, công cụ shell/ghi tệp/GUI, admin RPC. Xác nhận tắt
   Cloud Agent làm mất kết nối; kiểm thử thu hồi grant và rollback.

## 4. Phân biệt ba loại sự cố

| Dấu hiệu | Kiểm tra ở đâu | Không được suy ra |
| --- | --- | --- |
| `/health` thành công | HTTP Worker | Agent đang online |
| Device đã đăng ký nhưng agent offline | UDB Manager, Relay status | OAuth bị lỗi |
| Access trả 401 + OAuth challenge | Cloudflare Access path/policy | Người dùng đã đăng nhập |
| ChatGPT Connected nhưng không có tool | Plugin/tool discovery, grant, agent | Được phép thực hiện lệnh |

Nếu lệnh preflight báo **403** ở chế độ Access hoặc chỉ nhận **401 của
JWT nội bộ**, **chưa được** coi là Managed OAuth đã bật. Không tự nới
phạm vi policy để làm bài kiểm thử chuyển xanh.

## 5. Ranh giới và rollback

- Chỉ thực hiện đối với máy/tài khoản do chủ sở hữu đồng ý; không chia sẻ
  admin key, mã mời, device token, OAuth token, email grant hoặc PIN trên GitHub.
- Cloudflare là relay trung gian, **không** cung cấp mã hóa đầu-cuối cho
  nội dung RPC; hạn chế dữ liệu nhạy cảm.
- Nếu không đạt, giữ `UDB_AUTH_MODE` ở mặc định `jwt` chưa cấu hình
  (MCP từ chối), hoặc tắt riêng Access app trên MCP path; không sửa WebSocket.
- Dừng Cloud Agent trên GUI khi không dùng; thu hồi thiết bị theo quy trình
  admin nếu thông tin đăng ký bị lộ. Không tự phát lại một claim đã timeout.

Nguồn kỹ thuật:
- https://developers.cloudflare.com/workers/configuration/cloudflare-access/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/
- [Cloud relay prototype](cloudflare-relay-prototype.md)
- [Cloudflare Access code integration](cloudflare-access-managed-oauth.md)
