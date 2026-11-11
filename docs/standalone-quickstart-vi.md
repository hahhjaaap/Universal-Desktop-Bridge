# Khởi động UDB qua Cloudflare

Chạy trên Windows bằng tài khoản đã ghép nối thiết bị:

```powershell
udb setup
udb start
```

`udb setup` hiển thị URL của thiết bị đã ghép hoặc nhận mã mời Cloudflare
một lần. Dán URL MCP vào ChatGPT với OAuth. Gọi `bridge_status` trong
ChatGPT để xác minh kết nối. `udb mcp-config` xuất cấu hình HTTPS của
thiết bị, hoặc danh sách rỗng trước khi ghép nối.

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
