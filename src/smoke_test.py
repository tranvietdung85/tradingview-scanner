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

    fetcher = BinanceFetcher([args.symbol], args.interval)
    try:
        raw = fetcher.get_klines(args.symbol, args.interval, limit=args.limit)
    except Exception as e:
        # Graceful degradation for restricted region errors on CI
        msg = str(e)
        if 'restricted location' in msg.lower() or 'service unavailable' in msg.lower() or '451' in msg:
            logger.error('Binance API bị hạn chế ở môi trường này: %s', e)
            degraded_msg = (
                'Smoke Test: Không truy cập được Binance Spot từ môi trường CI (hạn chế vùng).\n'
                'Bạn vẫn có thể test logic cục bộ hoặc dùng proxy/alternative data source.'
            )
            if args.to_telegram:
                try:
                    bot = TelegramBot(parse_mode=args.parse_mode)
                    bot.send_message(degraded_msg)
                except Exception as te:
                    logger.error('Gửi Telegram (degraded) thất bại: %s', te)
                    print(degraded_msg)
            else:
                print(degraded_msg)
            return
        raise
    df = fetcher.to_dataframe(raw)
    if df.empty:
        raise RuntimeError('No data fetched; check symbol/interval or network.')

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
            signals['abw'] = f"AB_W={ab_w:.2f} (weekly, len=20, mult=2.0)"
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
