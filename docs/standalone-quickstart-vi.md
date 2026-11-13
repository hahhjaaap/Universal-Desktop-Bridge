# Khởi động UDB qua Cloudflare

> **UDB 0.12.0 documentation review (2026-11-13):** Current source targets UDB 0.12.0; installed Windows releases and deployed Cloudflare services must be verified independently. See [version/status](current-version.md).

**Lưu ý bản cài:** Mã nguồn `main` ngày 13/11/2026 đã có các thay đổi dọn
Tunnel/Aura và sửa bước kiểm thử Qt trên Windows, nhưng bản Windows phát hành
`v0.12.0` ngày 11/11/2026 không tự cập nhật theo các commit đó. Xác minh
`udb --version`, `udb version --json` và [trạng thái phát hành](release-security.md)
trước khi cài hoặc nâng cấp. Quy trình phát hành mới đang bị chặn an toàn
khi nhánh GitHub `main` chưa được bật bảo vệ.

Chạy trong PowerShell trên **chính máy Windows** với tài khoản chủ máy (chỉ
thực hiện ghép nối khi người dùng có mặt):

```powershell
udb setup
udb start
```

`udb setup` hiển thị URL của thiết bị đã ghép hoặc nhận mã mời Cloudflare
một lần. Dán URL MCP vào ChatGPT với OAuth. Gọi `bridge_status` trong
ChatGPT để xác minh kết nối. `udb mcp-config` xuất cấu hình HTTPS của
thiết bị, hoặc danh sách rỗng trước khi ghép nối. Cờ cũ `--edit`
không còn mở wizard Tunnel và không thay thế quy trình `udb setup` hiện hành.
Lỗi ghép nối phải được xử lý theo Cloudflare; không nhập runtime API key
hoặc Tunnel ID vào trình thiết lập mới.

## Xem Live

```powershell
udb live
udb live --gui
```

`udb live` theo dõi lời gọi công cụ trong terminal. `udb live --gui`,
**UDB Live** trong Start Menu và **Ctrl+Alt+U** mở cửa sổ nhật ký.
Trong UDB Manager, **Ctrl+Shift+L** mở tab Live.

Các lời gọi qua Cloudflare hiện `CALLING`, sau đó là `PASS`, `ERROR`
hoặc `RUNNING` khi tác vụ được giao chạy nền. Nhật ký có mã lời gọi và
thời gian xử lý. Bạn có thể đóng cửa sổ Live trong khi Cloud Agent vẫn chạy.

## Chẩn đoán

```powershell
udb status --json
udb doctor --cloud --json
udb logs --once
```

`udb gui` mở bảng duyệt quyền và thao tác bàn giao đăng nhập ngay trên
Windows. `udb quickstart` chỉ chạy tiến trình hỗ trợ Windows để kiểm tra
trước khi ghép nối. UDB dùng Cloudflare cho các kết nối MCP.
