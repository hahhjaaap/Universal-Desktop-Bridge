# UDB độc lập — mở nhanh như một ứng dụng Windows

**Mục tiêu:** UDB hoạt động độc lập với Desktop Commander, chạy một lần và
sử dụng lại ngay. Ưu tiên ít thao tác, khởi động nhanh, không nâng quyền
ngầm hoặc cấp quyền AI cho toàn bộ máy.

## Ba trải nghiệm khác nhau

| Mục tiêu | Cách sử dụng | Phụ thuộc |
| --- | --- | --- |
| Chạy UDB độc lập trên máy Windows | `udb quickstart` | Không cần Cloudflare, ChatGPT, Desktop Commander, Python bên ngoài nếu dùng EXE đóng gói |
| Dùng UDB với client MCP cục bộ có hỗ trợ stdio | `udb mcp-config` | Client cục bộ cần nhập cấu hình MCP do UDB tạo |
| Gọi UDB từ ChatGPT trên web/máy khác | Pairing thiết bị + relay HTTPS + OAuth + grant | Phải hoàn tất quy trình kết nối và xác thực riêng; không được gọi là đã kết nối chỉ vì local manager chạy |

**Lưu ý:** ChatGPT web không thể tự mở tiến trình stdio trên máy Windows
của người dùng bằng cách đọc JSON từ `udb mcp-config`.
Muốn điều khiển qua ChatGPT, UDB cần một kết nối MCP từ xa thực sự
được ChatGPT hỗ trợ và đã cấp quyền.

## Dùng độc lập ngay sau khi cài đặt

Mở PowerShell của **chính tài khoản Windows đang sử dụng** và chạy:

```powershell
udb quickstart
udb gui
```

`udb quickstart` chỉ khởi động/reuse UDB manager trong **offline mode**.
Không cần nhập token, không chạy wizard, không dùng Cloudflare hoặc tạo
mới pairing. Nếu manager đang dùng một kết nối online khác, lệnh
**từ chối**, không dừng hay đổi chế độ của manager hiện tại. Lệnh có
thể chạy lại nhiều lần và luôn kiểm tra trạng thái thực tế. Nếu manager
chưa sẵn sàng, nó báo lỗi, không in READY giả.

Để mở UDB cùng Windows **chỉ với lựa chọn rõ ràng của người dùng**:

```powershell
udb quickstart --autostart
```

Tùy chọn này tạo cấu hình tự khởi động tại đăng nhập của chính tài
khoản Windows. Nó chỉ cho phép profile mới hoặc profile đã ở local mode;
không được dùng để ghi đè chế độ khởi động của một profile đang ghép
nối Cloudflare hoặc Tunnel. Không cần quyền Administrator.

Tắt tự khởi động khi không muốn sử dụng:

```powershell
udb autostart disable
```

## Dùng với một client MCP trên cùng máy

```powershell
udb mcp-config
```

UDB sẽ in ra cấu hình JSON `mcpServers` theo đúng binary hoặc Python
runtime đang sử dụng. Sao chép JSON vào **client MCP cục bộ** cho phép
cấu hình `stdio`; client sẽ tự chạy tiến trình `udb serve` cho
chính nó. Đừng dùng JSON này như một URL Cloudflare hoặc đăng nó công khai,
vì có thể chứa các đường dẫn máy riêng.

`quickstart` không tự đăng ký một client và không thay đổi quyền
đọc/ghi. Công cụ terminal, desktop và các thao tác nhạy cảm vẫn chịu
giới hạn theo quyền được chủ máy cấp.

## Khi muốn dùng từ ChatGPT, không cần Desktop Commander

Một bản UDB remote hoàn chỉnh cần:
1. ChatGPT nhận diện và kích hoạt **plugin/MCP connector UDB** của bạn.
2. Owner xác nhận thiết bị và đăng nhập OAuth trên kết nối riêng.
3. Worker/relay kiểm tra danh tính, thiết bị và grant từng công cụ.
4. Windows Cloud Agent kết nối, và một lần gọi `bridge_status` thật từ
   ChatGPT thành công. Muốn đọc file, cần dự án đã đăng ký và quyền đọc cụ thể.

Hiện các kiểm chứng trên chưa hoàn tất đủ để gọi remote là plug-and-play.
Một kết quả `udb quickstart` READY **không** chứng minh ChatGPT đã
truy cập máy. Không tự bật quyền terminal/desktop từ relay chỉ để
giảm số bước kết nối.

## Lệnh chẩn đoán nhanh

```powershell
udb quickstart --json
udb status --json
udb doctor --json
udb logs --once
```

Các lệnh kiểm tra cục bộ không yêu cầu đăng nhập Cloudflare. Chỉ dùng
`udb doctor --cloud --json` khi chủ máy chủ động kiểm tra public
preflight của thiết bị đã ghép nối, để phân biệt relay với manager.

## Tiêu chí để đạt trải nghiệm như Desktop Commander

- Một installer đã ký và hoạt động trên Windows 11 x64 sạch.
- Khởi động nhanh, sẵn sàng cả sau khởi động lại máy và có trạng thái rõ ràng.
- Pairing và kết nối UDB với ChatGPT một lần; các lần sau tự kết nối lại
  **mà không bỏ qua OAuth và quyền của chủ máy**.
- Plugin UDB trực tiếp có catalog công cụ, không phụ thuộc vào plugin
  Desktop Commander hoặc thao tác Cloudflare thủ công cho người dùng cuối.
- Kiểm thử ít nhất một lần đọc file thật, thu hồi quyền và xử lý mất mạng
  không phát lại thao tác có kết quả chưa chắc chắn.

`quickstart` giải quyết **đường sử dụng local** trước; phần remote
cần hoàn thành P0-A/P0-B và phát hành connector phù hợp.
