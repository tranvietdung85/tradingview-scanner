import os
import logging
import argparse
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
import yaml
from typing import Dict

from src.scan_abw_volume import scan, format_matches_markdown
from src.telegram_bot import TelegramBot

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def load_config(path: str = 'config.yaml') -> Dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file {path} not found. Create it from config.example.yaml")
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def run_scan_job(cfg: Dict, dry_run: bool = False):
    cs = (cfg.get('custom_signals') or {}).get('abw_volume_spike') or {}
    abw_lt = float(cs.get('abw_lt', 1.0))
    vol_ma_len = int(cs.get('volume_ma_length', 20))
    vol_mult = float(cs.get('volume_multiplier', 10.0))
    weekly_len = int(cs.get('bb_length', 20))
    weekly_mult = float(cs.get('bb_mult', 2.0))
    top_n = int((cfg.get('binance') or {}).get('top_n_scan', 50))
    sleep_s = float((cfg.get('binance') or {}).get('scan_sleep', 0.1))

    matches = scan(
        top_n=top_n,
        abw_lt=abw_lt,
        vol_ma_len=vol_ma_len,
        vol_mult=vol_mult,
        weekly_len=weekly_len,
        weekly_mult=weekly_mult,
        sleep_s=sleep_s,
    )
    text = format_matches_markdown(matches, top_n, abw_lt, vol_ma_len, vol_mult)
    if dry_run:
        print("----- MESSAGE PREVIEW (dry-run) -----")
        print(text)
    else:
        tg_cfg = (cfg.get('telegram') or {})
        bot = TelegramBot(tg_cfg.get('bot_token'), tg_cfg.get('chat_id'), tg_cfg.get('parse_mode','Markdown'))
        bot.send_message(text)
        logger.info("Đã gửi kết quả quét hằng ngày lên Telegram.")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Lên lịch quét AB_W + Volume hàng ngày và gửi Telegram')
    parser.add_argument('--run-now', action='store_true', help='Chạy quét ngay một lần rồi thoát (dùng để test)')
    parser.add_argument('--dry-run', action='store_true', help='Không gửi Telegram, chỉ in nội dung sẽ gửi')
    args = parser.parse_args()

    cfg = load_config()
    if args.run_now:
        run_scan_job(cfg, dry_run=args.dry_run)
        return

    hhmm = ((cfg.get('scheduler') or {}).get('scan_time') or '06:45').strip()
    try:
        hour, minute = [int(x) for x in hhmm.split(':', 1)]
    except Exception:
        raise ValueError("scheduler.scan_time phải có định dạng HH:MM, ví dụ '06:45'")

    # Dùng thời gian LOCAL (không set timezone) để khớp giờ máy Windows của bạn
    scheduler = BlockingScheduler()
    scheduler.add_job(lambda: run_scan_job(cfg), 'cron', hour=hour, minute=minute, id='daily_abw_scan')
    logger.info("Lên lịch quét hằng ngày lúc %02d:%02d (giờ local).", hour, minute)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Dừng lịch quét.")


if __name__ == '__main__':
    main()
