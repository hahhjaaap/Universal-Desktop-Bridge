# Checklist thiết lập UDB ↔ Cloudflare ↔ ChatGPT

> **Hướng dẫn cho source hiện tại, không phải bằng chứng đã kết nối.** Kiểm tra riêng
> phiên bản UDB trên Windows, Worker đang triển khai, Cloudflare Access/OAuth,
> quyền thiết bị và lời gọi MCP thực tế. PR/code merge không tự cập nhật EXE hoặc Worker.

## 1. Phân biệt các lớp và endpoint

1. **Windows device:** mỗi máy có một `device_id`, pairing credential riêng và
   Cloud Agent riêng. Không sao chép token hoặc pairing file giữa các máy.
2. **Cloudflare relay:** Windows Cloud Agent mở WebSocket outbound tới
   `/v1/devices/DEVICE_ID/connect`. Không áp dụng Access policy toàn Worker
   làm chặn WebSocket này.
3. **MCP per-device:** `/v1/devices/DEVICE_ID/mcp`, dùng cho chế độ từng máy
   hoặc tương thích cũ.
4. **MCP account Fleet:** `/v1/account/mcp`, một endpoint OAuth cho một tài khoản
   quản lý nhiều máy đã liên kết. `list_devices` liệt kê máy; mọi công cụ thao
   tác trên máy phải nhận `device_id` tường minh. Không tự failover sang máy khác.
5. **Windows permissions:** catalog hiện công cụ không có nghĩa máy đã cấp quyền.
   Quyền project, files, terminal, desktop và background vẫn được chủ máy cấp
   riêng trên Windows.

`udb mcp-config` luôn in URL per-device để giữ tương thích. Khi Fleet bật và máy
đã liên kết, dùng URL `/v1/account/mcp` do `udb setup` hiển thị; chỉ thêm URL
này một lần vào ChatGPT.

**Không được coi** `/health = 200`, Cloud Agent đang chạy, pairing hợp lệ hoặc
nhãn Connected của ChatGPT là bằng chứng end-to-end.

## 2. Chuẩn bị môi trường staging

- Xác nhận đúng bản bằng `udb --version`, `udb version --json`; đối chiếu source
  commit, Windows EXE và Worker revision riêng biệt.
- Dùng Worker, Durable Object namespace, secrets, Access applications và thiết
  bị thử riêng. Không dùng Worker staging đang phục vụ máy thật để thử deployment
  hoặc thay đổi namespace.
- Access MCP phải bảo vệ chính xác resource đang dùng: per-device MCP hoặc
  `/v1/account/mcp`. Browser approval dùng Access application riêng cho
  `/v1/setup/enrollments/*/approval`, audience riêng.
- Cấu hình `UDB_AUTH_MODE=cloudflare-access`, Access team/audience đã xác minh,
  `UDB_ENROLLMENT_ACCESS_AUD` riêng và danh sách chủ sở hữu theo immutable
  subject `https://TEAM.cloudflareaccess.com#USER-UUID`. Email header không phải
  bằng chứng chủ sở hữu.
- Enrollment/Fleet chỉ hoạt động khi operator chủ động cấu hình các cờ phù hợp:
  `UDB_ENABLE_PRIVATE_ENROLLMENT=true`,
  `UDB_ENABLE_BROWSER_ENROLLMENT=true`,
  `UDB_ENABLE_LOCAL_TOOL_SYNC=true`; riêng account Fleet cần thêm
  `UDB_ENABLE_ACCOUNT_FLEET=true`. Fleet yêu cầu Cloudflare Access mode và
  `UDB_TENANT_POLICY` không được cấu hình.
- Giữ nguyên các relay-wide owner/companion gates, per-device grants và quyền
  Windows hiện hữu. Không mở rộng Access policy, không bật production, không
  thay credential hay Durable Object namespace nếu chưa được phê duyệt riêng.

Xem thêm [automatic setup và recovery](automatic-setup.md) và
[account Fleet MCP](account-fleet-mcp.md).

## 3. Trình tự trên từng máy Windows

1. Cài bản UDB đã được kiểm tra. Bản stable v0.12.0 đã phát hành có thể chưa
   chứa thay đổi source mới hơn; kiểm tra `udb --version` thay vì suy đoán.
2. Mở PowerShell có chủ máy trực tiếp và chạy:

   ```powershell
   udb setup
   ```

3. Với máy mới, UDB tạo yêu cầu enrollment có thể khôi phục. So sánh
   `device_id` và fingerprint hiện trên Windows với trang Access approval,
   rồi chủ sở hữu tự đăng nhập và approve hoặc reject. Không nhập admin key,
   invitation, device token hay relay URL vào PowerShell.
4. UDB lưu token trong Windows Credential Manager, tái sử dụng hoặc khởi động
   Cloud Agent với terminal access tắt. Tùy chọn Windows sign-in autostart chỉ
   được bật sau khi chủ máy đồng ý; từ chối được ghi nhớ.
5. Với máy đã ghép từ trước, `udb setup` giữ nguyên token/pairing. Nếu Fleet
   được bật nhưng máy chưa liên kết, nó yêu cầu chủ sở hữu xác nhận link riêng;
   không re-enroll và không xoay token.
6. Mở handoff page. Nếu trang hiển thị `/v1/account/mcp`, thêm endpoint này
   một lần trong ChatGPT và tự hoàn tất OAuth. Nếu hiển thị URL per-device,
   đó là chế độ cũ; không tự đổi sang account URL khi Fleet chưa bật.
7. Trong Fleet mode, gọi `list_devices`, chọn đúng `device_id`, rồi gọi
   `bridge_status` trên máy đó. Sau đó chỉ dùng các công cụ được grant cho
   đúng chủ sở hữu và máy đích.
8. Nếu cần quyền Windows rộng, chủ máy tự mở UDB Manager hoặc chạy
   `udb --access computer` và đọc kỹ prompt. Không có MCP tool nào được phép
   tự cấp quyền Windows.

Không cài thêm plugin hoặc endpoint riêng cho từng máy trong Fleet mode.
Không coi tool discovery là quyền thực thi.

## 4. Kiểm tra và chẩn đoán

Các lệnh sau chỉ đọc trạng thái; không enrollment, không ghi credential, không
mở browser, không khởi động process, không đổi autostart và không cấp quyền:

```powershell
udb setup --status
udb setup --no-browser
udb setup --json
udb status --json
udb doctor --cloud --json
```

`udb setup --status` chỉ trả mã 0 khi credential hợp lệ, Cloud Agent online và
có bằng chứng MCP xác thực mới. Trong Fleet mode, liên kết thiết bị với tài
khoản cũng phải được xác minh; status hiển thị URL `/v1/account/mcp` dùng chung.
Điều này chứng minh lời gọi MCP đã được relay ghi nhận, **không** chứng minh
danh tính ứng dụng ChatGPT độc lập; UDB không tự khai báo ChatGPT Connected từ
heartbeat hoặc tên client không đáng tin.

| Dấu hiệu | Kiểm tra | Không được suy ra |
| --- | --- | --- |
| `/health = 200` | Worker đang phản hồi | Agent online hoặc OAuth đã xác thực |
| Device đã pair nhưng offline | Cloud Agent, WebSocket, mạng và đúng device ID | OAuth bị lỗi |
| 401 / OAuth challenge | Access application, audience, DCR và consent | Đã đăng nhập thành công |
| `list_devices` trả offline/unverified | Đúng device ID, agent và owner binding | Được tự chọn máy thay thế |
| Tool hiển thị nhưng bị từ chối | Grant Windows tại máy đích, relay tool gates và project scope | Catalog đã cấp quyền |

Sau thay đổi catalog, refresh/reconnect plugin theo khả năng của ChatGPT.
Một client có fixed tool allowlist vẫn cần được cấu hình để hiển thị canonical
tools; refresh không thể cấp quyền hoặc thay Access policy.

## 5. Kiểm thử từ chối và rollback

Trong staging cô lập, kiểm tra ít nhất: hai máy một tài khoản; thêm máy thứ ba;
hai tài khoản không truy cập chéo; máy offline; Agent dừng/khởi động lại; mất
mạng; từ chối hoặc hết hạn approval; OAuth lỗi/hết hạn; thu hồi token; thu hồi
quyền trên một máy không ảnh hưởng máy khác. Ghi rõ mô phỏng và nghiệm thu thật
là hai loại bằng chứng khác nhau.

Nếu rollout thất bại, rollback Worker về version đã ghi nhận hoặc tắt riêng
Fleet/browser-enrollment flags. Giữ namespace, secrets, token, pairing files và
thiết bị hiện hữu; không revoke thiết bị đang dùng để thử nếu chưa có xác nhận
của chủ sở hữu. Không tự replay một lời gọi mutation có kết quả không rõ.

Nguồn kỹ thuật: [Cloudflare Access](https://developers.cloudflare.com/workers/configuration/cloudflare-access/),
[Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/),
[project-read acceptance](cloudflare-project-read-acceptance.md),
[release security](release-security.md).
