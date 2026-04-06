# Hướng dẫn Deploy lên Railway

## Cấu trúc thư mục

```
tiktok-bot/
├── viewbot.py          # Core bot engine (nâng cấp từ 3 file cũ)
├── telegram_bot.py     # Giao diện Telegram
├── requirements.txt    # Thư viện Python
├── Procfile            # Lệnh khởi động Railway
├── railway.json        # Cấu hình Railway
├── runtime.txt         # Phiên bản Python
├── proxies.txt         # Danh sách proxy (tuỳ chọn)
└── .env.example        # Ví dụ biến môi trường
```

---

## Bước 1 – Tạo Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gửi `/newbot`
3. Đặt tên bot (ví dụ: `TikTok View Bot`)
4. Đặt username kết thúc bằng `bot` (ví dụ: `mytiktokview_bot`)
5. Sao chép **Bot Token** – dạng: `7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

---

## Bước 2 – Tạo tài khoản Railway

1. Truy cập [railway.app](https://railway.app)
2. Đăng nhập bằng GitHub (miễn phí $5/tháng, đủ dùng)

---

## Bước 3 – Deploy lên Railway

### Cách A – Deploy qua GitHub (khuyến nghị)

1. **Push code lên GitHub:**
   ```bash
   cd tiktok-bot
   git init
   git add .
   git commit -m "Initial deploy"
   git remote add origin https://github.com/username/tiktok-bot.git
   git push -u origin main
   ```

2. **Tạo project Railway:**
   - Vào [railway.app/new](https://railway.app/new)
   - Chọn **Deploy from GitHub repo**
   - Chọn repository `tiktok-bot`
   - Chọn branch `main`

3. **Đặt biến môi trường:**
   - Vào tab **Variables**
   - Thêm: `TELEGRAM_BOT_TOKEN` = `<token của bạn>`
   - *(Tuỳ chọn)* `PROXIES` = `ip1:port1,ip2:port2,...`

4. Railway sẽ tự động detect `Procfile` và deploy!

### Cách B – Deploy bằng Railway CLI

```bash
# Cài Railway CLI
npm install -g @railway/cli

# Đăng nhập
railway login

# Vào thư mục project
cd tiktok-bot

# Tạo project mới
railway init

# Đặt biến môi trường
railway variables set TELEGRAM_BOT_TOKEN=your_token_here

# Deploy
railway up
```

---

## Bước 4 – Kiểm tra bot

1. Mở Telegram, tìm bot của bạn
2. Gửi `/start` – bot phản hồi = thành công!
3. Gửi `/help` để xem tất cả lệnh

---

## Danh sách lệnh Telegram

| Lệnh | Chức năng |
|------|-----------|
| `/start` | Giới thiệu + hiển thị **IP public server** |
| `/view <url>` | Bắt đầu gửi view |
| `/stop` | Dừng bot |
| `/stats` | Xem thống kê live |
| `/config` | Xem cấu hình + IP server |
| `/setworkers 2000` | Đặt số luồng (10–10000) |
| `/setrps 300` | Giới hạn request/giây |
| `/setlimit 5000` | Tự dừng khi đủ view (0=vô hạn) |
| `/addproxy ip:port` | Thêm 1 proxy thủ công |
| `/clearproxy` | Xoá tất cả proxy |
| Gửi file `.txt` | **Auto import proxy hàng loạt** |

## Import Proxy Hàng Loạt (tính năng mới)

Chỉ cần gửi file `.txt` vào chat – bot tự động nhận diện và import.

**Định dạng hỗ trợ trong cùng 1 file:**

| Định dạng | Ví dụ |
|-----------|-------|
| `ip:port` | `209.50.168.96:3129` |
| `ip:port:user:pass` | `31.59.20.176:6754:bedkyroi:nvqk8r8zeacq` |
| `user:pass@ip:port` | `bedkyroi:nvqk8r8zeacq@31.59.20.176:6754` |

Bot sẽ hiển thị:
- Số proxy hợp lệ tìm được
- Số proxy thêm mới (loại trùng lặp)
- Preview 5 proxy đầu tiên
- Tổng proxy hiện tại trong session

---

## Ví dụ sử dụng

```
# 1. Gửi view không giới hạn
/view https://www.tiktok.com/@user/video/7340000000000000000

# 2. Đặt 1000 workers trước
/setworkers 1000

# 3. Tự dừng khi đạt 10.000 view
/setlimit 10000
/view https://www.tiktok.com/@user/video/7340000000000000000

# 4. Dừng thủ công
/stop
```

---

## Thêm Proxy

**Qua lệnh Telegram:**
```
/addproxy 123.45.67.89:8080
/addproxy user:pass@123.45.67.89:3128
```

**Qua biến môi trường Railway:**
```
PROXIES=ip1:port1,ip2:port2,user:pass@ip3:port3
```

**Qua file proxies.txt** (chỉ khi chạy local):
```
123.45.67.89:8080
user:pass@123.45.67.89:3128
```

---

## Chạy Local (thay thế Railway)

```bash
cd tiktok-bot

# Cài thư viện
pip install -r requirements.txt

# Copy và sửa file env
cp .env.example .env
# Sửa TELEGRAM_BOT_TOKEN trong file .env

# Chạy bot
python telegram_bot.py
```

---

## Những cải tiến so với file cũ

| Tính năng | Cũ | Mới (v5.0) |
|-----------|-----|-------------|
| Device database | 5-14 devices | 21 devices (đa dạng hơn) |
| Thuật toán signature | Đơn giản / chưa đúng | X-Gorgon chính xác |
| Proxy support | Cơ bản | Rotation + async lock |
| Rate limiting | Chưa có / cơ bản | Token bucket adaptive |
| Điều khiển | CLI terminal | Telegram Bot |
| Deploy | Windows local | Railway cloud |
| Workers | Fixed | Tự động theo CPU |
| Giới hạn view | Không | Có (tự dừng) |
| Thống kê live | Console | Telegram message update |

---

> ⚠️ **Disclaimer:** Chỉ dùng cho mục đích học tập và nghiên cứu.
