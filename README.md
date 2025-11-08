# TradingView-Style Binance Reporter

Script Python lấy dữ liệu giá Spot Binance, tính chỉ báo (EMA, RSI, MACD) và gửi báo cáo hoặc tín hiệu về Telegram.

## Tính năng
- Lấy giá và nến từ Binance (binance-connector)
- Tính EMA (fast/slow), RSI, MACD
- Phát hiện các tín hiệu: EMA crossover, MACD cross, RSI overbought/oversold
- Gửi báo cáo định kỳ (cron) và gửi ngay khi xuất hiện tín hiệu
- Cấu hình qua `config.yaml` hoặc biến môi trường

## Cài đặt
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Tạo Telegram Bot
1. Mở @BotFather trên Telegram
2. /newbot và lấy BOT_TOKEN
3. Lấy chat_id: gửi tin nhắn đến bot, sau đó gọi `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates` và đọc `chat.id`

## Cấu hình
Sao chép file mẫu:
```powershell
Copy-Item config.example.yaml config.yaml
```
Sửa `config.yaml` với token và chat id hoặc đặt trong `.env`:
```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

## Chạy
```powershell
python src/main.py
```
Dừng bằng Ctrl+C.

### Chế độ test nhanh
Giảm lượng dữ liệu và bỏ MACD để chạy thử nhanh:
```powershell
python -m src.main --quick --oneshot
```
- `--quick`: bật quick_mode (ít nến hơn, bỏ MACD, khoảng chạy signal check có thể giảm)
- `--oneshot`: gửi một báo cáo rồi thoát (hữu ích để kiểm tra format Telegram)

Hoặc cấu hình trong `config.yaml` phần `testing`:
```yaml
testing:
	quick_mode: true
	fetch_limit: 80
	oneshot: true
```

## Mở rộng
- Thêm chỉ báo mới: chỉnh `indicators.py`
- Thêm cảnh báo tùy biến: mở rộng `generate_signals`
- Lưu lịch sử: ghi DataFrame ra CSV trong `periodic_report`
- Tạo unit test cho chỉ báo: mock DataFrame nhỏ để kiểm tra tín hiệu

## Ghi chú
- Endpoint public không cần API key
- Rate limit: đã thêm sleep nhỏ khi phân trang lịch sử (nếu mở rộng)
- Không dành cho tư vấn đầu tư; dùng cho mục đích kỹ thuật.

## Bảo mật & Secrets
- KHÔNG commit token/chat_id vào repo. Thay vào đó:
	1. Sao chép `.env.example` thành `.env` và điền:
		 - `TELEGRAM_BOT_TOKEN=...`
		 - `TELEGRAM_CHAT_ID=...`
	2. Đảm bảo `.gitignore` đã bỏ qua `.env` và `config.yaml`.
	3. Trong `config.yaml`, để trống `telegram.bot_token` và `telegram.chat_id` để code tự đọc từ `.env`.
- Nếu lỡ public hoá token, hãy vào @BotFather và rotate token ngay.

## Tự động chạy hằng ngày (không cần mở máy) với GitHub Actions
Bạn có thể để GitHub chạy quét và gửi kết quả lên Telegram mỗi ngày theo lịch (cron) mà không cần bật máy tính:

1) Đẩy code lên GitHub (private/public tuỳ bạn).

2) Vào Settings → Secrets and variables → Actions → New repository secret và tạo 2 secrets:
	 - `TELEGRAM_BOT_TOKEN`
	 - `TELEGRAM_CHAT_ID`

3) Workflow đã được tạo tại `.github/workflows/daily-scan.yml` với lịch mặc định 23:45 UTC (tương đương 06:45 giờ Việt Nam). Nếu muốn đổi giờ, sửa dòng `cron`:
```
# daily-scan.yml
on:
	schedule:
		- cron: '45 23 * * *'  # UTC
```
Ví dụ muốn 07:30 Việt Nam (UTC+7) thì là `30 0 * * *` theo UTC.

4) Workflow sẽ cài Python, cài dependencies và chạy:
```
python -m src.scan_abw_volume --top 50 --abw-lt 1.0 --vol-mult 10 --to-telegram
```
Bạn có thể chỉnh tham số trong file YAML này theo nhu cầu.

Lưu ý:
- GitHub Actions dùng UTC, cần quy đổi từ giờ địa phương sang UTC.
- Đảm bảo không vượt rate limit khi tăng `--top` quá lớn.
- Nếu gặp thông báo "restricted location / 451": dùng proxy hoặc mirror. Bạn có thể đặt biến môi trường secrets:
	- `PROXY_URL` (ví dụ: `http://user:pass@host:port`)
	- `BINANCE_BASE_URL` nếu muốn thử endpoint khác (ví dụ cổng phụ / region khác).
	Sau đó workflow sẽ tự đọc và cấu hình client.

## License
MIT (tuỳ chọn thêm nếu cần)
