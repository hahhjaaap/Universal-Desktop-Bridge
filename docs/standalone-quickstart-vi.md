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
```

Bạn cũng có thể mở **UDB Live** trong Start Menu hoặc nhấn **Ctrl+Alt+U**
sau khi cài shortcut. Trong UDB Manager, dùng **Ctrl+Shift+L**.
Trang Live nằm tại URL MCP hiện có với query `?view=live`.

Đăng nhập Cloudflare Access, chọn tab UDB và bấm **Bắt đầu Live**.
Phải bật quyền trình duyệt nền trong UDB Manager trên Windows và đã có
tab trong trình duyệt riêng UDB. Trong trang Live, **Space** bật/dừng,
**R** tải lại danh sách tab, **F** mở toàn màn hình và **Esc** dừng.

## Chẩn đoán

```powershell
udb status --json
udb doctor --cloud --json
udb logs --once
```

`udb gui` mở bảng duyệt quyền và thao tác bàn giao đăng nhập ngay trên
Windows. `udb quickstart` chỉ chạy tiến trình hỗ trợ Windows để kiểm tra
trước khi ghép nối. UDB dùng Cloudflare cho các kết nối MCP.
