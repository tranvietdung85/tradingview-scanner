import os
import argparse
import logging
from dotenv import load_dotenv

from src.fetcher import BinanceFetcher
from src.indicators import compute_indicators, generate_signals, compute_weekly_ab
from src.report import build_report
from src.telegram_bot import TelegramBot

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Smoke test: fetch -> indicators -> report -> Telegram (optional)')
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--interval', default='1h')
    parser.add_argument('--limit', type=int, default=120)
    parser.add_argument('--include-macd', action='store_true', help='Include MACD in quick test')
    parser.add_argument('--include-abw', action='store_true', help='Compute AB_W (weekly) and append to report')
    parser.add_argument('--to-telegram', action='store_true', help='Send to Telegram instead of printing')
    parser.add_argument('--parse-mode', default='Markdown')
    args = parser.parse_args()

    # If running in CI with restricted region, allow graceful fallback with degraded notice
    fetcher = BinanceFetcher([args.symbol], args.interval)
    raw = None
    try:
        raw = fetcher.get_klines(args.symbol, args.interval, limit=args.limit)
    except Exception as e:
        logger.exception('Lỗi lấy klines (không có fallback nào thành công): %s', e)
        degraded_msg = 'Smoke Test: Hoàn toàn không lấy được dữ liệu (Binance + mirrors + yfinance đều thất bại).'
        if args.to_telegram:
            try:
                bot = TelegramBot(parse_mode=args.parse_mode)
                bot.send_message(degraded_msg)
            except Exception:
                print(degraded_msg)
        else:
            print(degraded_msg)
        return

    source = fetcher.last_source or 'unknown'
    if source != 'binance_client':
        logger.warning('Dữ liệu dùng nguồn dự phòng: %s', source)
        if args.to_telegram:
            try:
                bot = TelegramBot(parse_mode=args.parse_mode)
                bot.send_message(f"[Cảnh báo] Dữ liệu lấy từ nguồn dự phòng: {source}")
            except Exception:
                pass
    df = fetcher.to_dataframe(raw)
    if df.empty:
        raise RuntimeError('No data fetched after fallback chain; kiểm tra symbol/interval hoặc mạng.')

    config = {
        'include_ema': True,
        'include_rsi': True,
        'include_macd': bool(args.include_macd),
        'ema': {'fast': 12, 'slow': 26},
        'rsi': {'period': 14, 'overbought': 70, 'oversold': 30},
        'macd': {'fast': 12, 'slow': 26, 'signal': 9},
    }
    df_ind = compute_indicators(df, config)
    signals = generate_signals(df_ind, config)

    # Optional AB_W attach
    if args.include_abw:
        try:
            ab_w = compute_weekly_ab(fetcher, args.symbol, '1w', 20, 2.0, limit=60)
            # Escape underscore for Telegram Markdown
            signals['abw'] = f"AB\\_W={ab_w:.2f} (weekly, len=20, mult=2.0)"
        except Exception as e:
            logger.exception('AB_W compute failed: %s', e)

    text = build_report(args.symbol, df_ind, signals, decimals=2)

    if args.to_telegram:
        try:
            bot = TelegramBot(parse_mode=args.parse_mode)
            bot.send_message(text)
        except Exception as e:
            logger.error('Gửi Telegram thất bại: %s', e)
            print('Report (local print fallback):')
            print(text)
    else:
        print('----- SMOKE TEST REPORT -----')
        print(text)


if __name__ == '__main__':
    main()
