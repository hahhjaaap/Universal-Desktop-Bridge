# Đăng ký UDB máy mới không cần mã mời (Private Enrollment)

> **Luồng legacy/compatibility:** với cài đặt mới, dùng `udb setup` và
> [hướng dẫn automatic setup](automatic-setup.md). `udb connect --enroll`
> bên dưới được giữ cho quy trình quản trị cũ; không dùng thay cho setup mới.

**Trạng thái: mã nguồn trong PR, chưa triển khai Cloudflare.** Quy trình này
dùng riêng cho chủ hệ thống hoặc máy được chủ hệ thống phê duyệt. Không có
đăng ký công khai và không tự cấp quyền Windows hoặc quyền ChatGPT.

## Trên máy Windows mới

Sau khi cài bản UDB chứa chức năng này, mở **PowerShell trong phiên Windows
trực tiếp của chủ máy**:

```powershell
udb connect --enroll
```

Mặc định UDB dùng relay hiện được chỉ định riêng:
`https://udb-private-relay-staging.hkhoinguyen72.workers.dev`.
Có thể thay bằng `--relay https://REVIEWED-RELAY.workers.dev` cho hệ thống
được quản trị riêng. Đây là URL máy chủ công khai, **không phải token**.

UDB tự tạo khóa đăng ký tạm thời và **token thiết bị độc lập**; chỉ gửi các
băm SHA-256 lên Worker. Terminal hiển thị **Device ID** và **mã xác nhận
10 ký tự** để chủ hệ thống so sánh với máy thật. Người dùng mới **không cần
biết/nhập admin key hay mã mời Cloudflare**.

UDB chờ tối đa 10 phút; nếu được duyệt sẽ lưu token cục bộ vào Windows
Credential Manager và ghi metadata công khai ở `cloud-pairing.json`.
Không có quyền desktop, file, shell hay dữ liệu chủ máy được cấp tự động.

Để chủ động bật Cloud Agent khi đăng nhập Windows, dùng:

```powershell
udb connect --enroll --autostart
udb start
udb mcp-config
```

`--autostart` vẫn tuân theo giới hạn owner-attended, không bật terminal
unattended. Khởi động phiên hiện tại vẫn cần `udb start`.
Sau khi đăng ký, trong ChatGPT thêm **custom MCP server** bằng URL do
`udb mcp-config` hiển thị và đăng nhập OAuth theo Access. Đây là bước
xác nhận **riêng**, không thể tự động thực hiện thay chủ tài khoản.

Nếu đã ghép máy bằng mã mời cũ, tiếp tục dùng `udb connect`; không
cần/không được tự ghi đè danh tính đã tạo.

### Máy đã ghép: tự kết nối khi đăng nhập Windows

Đối với máy đã ghép và giữ token trong Windows Credential Manager,
mở terminal Windows có chủ máy, chạy:

```powershell
udb connect --autostart --no-browser
udb autostart status --json
udb start
```

Không đăng ký lại hoặc tạo token mới. Khi chủ máy đăng nhập Windows lần
sau, Cloud Agent dùng token đã lưu để kết nối lại; mất mạng sẽ thử lại có
giới hạn, không lặp các thao tác ghi có kết quả chưa xác định.
Tắt bằng `udb autostart disable`. Bước cấp quyền OAuth trong ChatGPT
vẫn phải do người dùng xác nhận; tự chạy Cloud Agent **không** phải
tự động đăng nhập vào tài khoản ChatGPT.

## Trên máy quản trị UDB (máy đáng tin cậy)

Mở terminal có người dùng trong source checkout và cài Python environment
của UDB. Khóa quản trị được **nhập ẩn** và không lưu thành tham số hoặc
vào repository.

```powershell
python tools/approve_private_enrollment.py --list
python tools/approve_private_enrollment.py --approve DEVICE_ID
```

Chủ hệ thống **so sánh mã xác nhận hiển thị trên máy Windows mới** và nhập
vào cửa sổ quản trị. Chỉ duyệt máy mình nhận biết được. Có thể từ chối
trước khi phê duyệt:

```powershell
python tools/approve_private_enrollment.py --reject DEVICE_ID
```

Cấp mã mời cũ bằng `POST /v1/admin/pairings` vẫn hoạt động độc lập.
Nếu đăng ký có kết quả **không xác định** (mất mạng lúc approve, client không
lưu được Credential Manager), **không tự thử lại**, mà kiểm tra trạng thái
admin, thu hồi device qua endpoint đã có rồi khởi tạo yêu cầu mới.

## Bật dịch vụ có kiểm soát

Worker chỉ cho phép các API enrollment mới nếu **tất cả** điều kiện sau
được đáp ứng:

- Triển khai Worker từ commit được kiểm thử, review độc lập, rollback được.
- Biến môi trường `UDB_ENABLE_PRIVATE_ENROLLMENT=true` được đặt bằng
  quản trị Cloudflare, và `UDB_ADMIN_KEY` mạnh đã được lưu dạng **secret**,
  không được nhúng vào file cài, GitHub, tài liệu, hoặc máy khách.
- Cấu hình Cloudflare WAF/rate limiting và giám sát để chống spam yêu cầu.
  Durable Object có thêm hạn mức 4 yêu cầu/giờ/nguồn, 50 yêu cầu/giờ và
  tối đa 20 yêu cầu đang hiệu lực; đó **không thay thế WAF**.
- Chủ hệ thống tạo và phê duyệt yêu cầu trong terminal riêng. Chỉ danh
  tính/grant thiết bị đã được cấu hình trong Access/OAuth mới dùng được
  MCP. Ghép nối thành công **không tự bật Cloudflare Access grant**.
- Staging/production tách biệt, WebSocket device và custom MCP URL không
  bị chặn nhầm khi cấu hình Access theo path.

Mặc định nếu không bật biến môi trường, mọi API mới sẽ trả
`404 enrollment_disabled` và không tạo Device ID nào. Không bật
đăng ký công khai để 'làm cho test xanh'.

## Hợp đồng bảo mật và tình huống kiểm thử

| Trường hợp | Kết quả kỳ vọng |
|---|---|
| Không bật tính năng | 404; không tạo bản ghi |
| Máy tự yêu cầu, chưa được duyệt | pending; token thiết bị chưa có hiệu lực |
| Thiếu hoặc sai admin key | 401; không thể duyệt |
| Sai mã xác nhận | 403; không thể duyệt |
| Phê duyệt đúng, thiết bị mới | token hash được đăng ký một lần |
| Duyệt lặp lại / thiết bị đã đăng ký | từ chối; không thay token |
| Từ chối/yêu cầu hết hạn | không cấp token |
| Mạng lỗi khi phê duyệt | kết quả không xác định; không retry mutation |
| Máy mới mất kết nối/chưa được duyệt | không lưu local token |
| ChatGPT chưa xác thực | không có quyền MCP dù đã ghép |

Chứng thực end-to-end cuối cùng cần thực hiện qua **hai tài khoản và hai
máy thật**, một kết nối ChatGPT Custom MCP đã OAuth, các lệnh
`bridge_status` và `list_projects` đã cấp quyền, và các bài kiểm thử từ
chối truy cập chéo. Node/Python mock chỉ xác nhận logic, không chứng minh
kết nối Cloudflare thật.

Các quyền Windows và quyền ChatGPT phải được cấp và thu hồi độc lập.
