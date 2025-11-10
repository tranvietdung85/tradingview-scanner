import time
import logging
import math
import argparse
from typing import List, Dict
# from binance.spot import Spot  # replaced by resilient fetcher usage
import pandas as pd

from src.fetcher import BinanceFetcher
from src.indicators import compute_weekly_ab
from src.telegram_bot import TelegramBot
from dotenv import load_dotenv
import yaml
import os

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def load_config(path: str = 'config.yaml') -> Dict:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def list_top_usdt_symbols(fetcher: BinanceFetcher, top_n: int = 50) -> List[str]:
    tickers = fetcher.fetch_ticker_24hr() or []  # may be None -> []
    if not tickers:
        raise RuntimeError('Không lấy được danh sách 24h tickers từ Binance (client+HTTP).')
    pairs = []
    for t in tickers:
        sym = t.get('symbol')
        if not sym or not sym.endswith('USDT'):
            continue
        # exclude leveraged tokens
        if any(x in sym for x in ['UP', 'DOWN', '3L', '3S']):
            continue
        try:
            qv = float(t.get('quoteVolume', 0.0))
        except ValueError:
            qv = 0.0
        pairs.append((sym, qv))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in pairs[:top_n]]


def daily_volume_stats(fetcher: BinanceFetcher, symbol: str, ma_len: int = 20) -> Dict[str, float]:
    raw = fetcher.get_klines(symbol, '1d', limit=max(ma_len + 2, 30))
    df = fetcher.to_dataframe(raw)
    if df.empty or df['volume'].notna().sum() < ma_len + 1:
        return {"latest": math.nan, "ma": math.nan}
    vol_ma = df['volume'].rolling(ma_len).mean().iloc[-1]
    vol_latest = df['volume'].iloc[-1]
    return {"latest": float(vol_latest), "ma": float(vol_ma)}


def scan(fetcher: BinanceFetcher, top_n: int, abw_lt: float, vol_ma_len: int, vol_mult: float, weekly_len: int, weekly_mult: float, sleep_s: float):
    symbols = list_top_usdt_symbols(fetcher, top_n=top_n)
    logger.info("Scanning %d symbols: %s", len(symbols), ', '.join(symbols[:10]) + ('...' if len(symbols) > 10 else ''))

    matches = []
    for i, sym in enumerate(symbols, 1):
        try:
            ab_w = compute_weekly_ab(fetcher, sym, '1w', weekly_len, weekly_mult, limit=60)
            vols = daily_volume_stats(fetcher, sym, vol_ma_len)
            latest, ma = vols['latest'], vols['ma']
            if not (math.isnan(ab_w) or math.isnan(latest) or math.isnan(ma)):
                cond = (ab_w < abw_lt) and (latest > vol_mult * ma)
                if cond:
                    logger.info("MATCH: %s | AB_W=%.2f < %.2f | Vol=%.0f > %.1fx MA%d=%.0f", sym, ab_w, abw_lt, latest, vol_mult, vol_ma_len, ma)
                    matches.append({"symbol": sym, "ab_w": ab_w, "vol": latest, "vol_ma": ma})
                else:
                    logger.debug("No match: %s | AB_W=%.2f, Vol=%.0f, MA=%0.f", sym, ab_w, latest, ma)
        except Exception as e:
            logger.exception("Error scanning %s: %s", sym, e)
        time.sleep(sleep_s)
    return matches


def format_matches_markdown(matches: List[Dict], top_n: int, abw_lt: float, vol_ma_len: int, vol_mult: float) -> str:
    abw_label = "AB\\_W"  # escape underscore for Telegram Markdown
    if not matches:
        return (f"Kết quả quét {abw_label} + Volume\n"
                f"Không có mã nào thỏa điều kiện ({abw_label} < {abw_lt}, Volume > {vol_mult}x MA{vol_ma_len})\n"
                f"Top {top_n} cặp USDT.")
    # Sort
    matches = sorted(matches, key=lambda x: x['ab_w'])
    lines = [
        f"Kết quả quét {abw_label} + Volume",
        f"Điều kiện: {abw_label} < {abw_lt}, Vol > {vol_mult}x MA{vol_ma_len}",
        f"Top {top_n} cặp USDT theo khối lượng 24h",
        "",
        f"Symbol | {abw_label} | Vol / MA (x)"
    ]
    for m in matches:
        vol = m['vol']
        ma = m['vol_ma'] if m['vol_ma'] else 0.0
        ratio = vol / ma if ma else float('nan')
        lines.append(f"{m['symbol']} | {m['ab_w']:.2f} | {vol:.0f}/{ma:.0f} ({ratio:.1f}x)")
        if len("\n".join(lines)) > 3500:  # avoid hitting Telegram 4096 char limit
            lines.append("... (rút gọn)")
            break
    return "\n".join(lines)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Scan USDT pairs for AB_W + Volume spike condition')
    parser.add_argument('--top', type=int, default=50, help='Top-N USDT pairs by 24h quote volume to scan')
    parser.add_argument('--abw-lt', type=float, default=1.0, help='Threshold: AB_W must be less than this value')
    parser.add_argument('--vol-ma-len', type=int, default=20, help='Daily volume moving average length')
    parser.add_argument('--vol-mult', type=float, default=10.0, help='Volume multiplier over MA to trigger')
    parser.add_argument('--bb-len', type=int, default=20, help='Bollinger length (weekly)')
    parser.add_argument('--bb-mult', type=float, default=2.0, help='Bollinger multiplier (weekly)')
    parser.add_argument('--sleep', type=float, default=0.1, help='Sleep between symbols to respect rate limit')
    parser.add_argument('--verbose', action='store_true', help='Show per-symbol diagnostics (AB_W, volume, MA)')
    parser.add_argument('--to-telegram', action='store_true', help='Gửi kết quả (hoặc thông báo không có mã) lên Telegram')
    parser.add_argument('--dry-run-telegram', action='store_true', help='Không gửi thật, chỉ in nội dung sẽ gửi')
    parser.add_argument('--notify-on-fail', action='store_true', help='Nếu lỗi (ví dụ API bị chặn), gửi thông báo thất bại lên Telegram thay vì crash')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Allow overriding from config.yaml if present
    cfg = load_config()
    cs = (cfg.get('custom_signals') or {}).get('abw_volume_spike') or {}
    abw_lt = float(cs.get('abw_lt', args.abw_lt))
    vol_ma_len = int(cs.get('volume_ma_length', args.vol_ma_len))
    vol_mult = float(cs.get('volume_multiplier', args.vol_mult))
    weekly_len = int(cs.get('bb_length', args.bb_len))
    weekly_mult = float(cs.get('bb_mult', args.bb_mult))

    try:
        fetcher = BinanceFetcher([], '1d')
        matches = scan(
            fetcher=fetcher,
            top_n=args.top,
            abw_lt=abw_lt,
            vol_ma_len=vol_ma_len,
            vol_mult=vol_mult,
            weekly_len=weekly_len,
            weekly_mult=weekly_mult,
            sleep_s=args.sleep,
        )
    except Exception as e:
        logger.exception("Scan failed: %s", e)
        if args.to_telegram and args.notify_on_fail:
            tg_cfg = (cfg.get('telegram') or {})
            bot = TelegramBot(tg_cfg.get('bot_token'), tg_cfg.get('chat_id'), tg_cfg.get('parse_mode','Markdown'))
            bot.send_message(f"Scan thất bại: {str(e)}\nCó thể do hạn chế vùng địa lý của API khi chạy trên môi trường CI.")
            logger.info("Đã gửi thông báo lỗi lên Telegram.")
            return
        raise

    if not matches:
        logger.info("No matches found with current thresholds.")
    else:
        df = pd.DataFrame(matches).sort_values(by=['ab_w'])
        print("\nMatches (sorted by AB_W):")
        print(df.to_string(index=False))

    if args.to_telegram:
        text = format_matches_markdown(matches, args.top, abw_lt, vol_ma_len, vol_mult)
        # append fallback source if not primary
        fetch_source = getattr(fetcher, 'last_source', 'unknown')
        if fetch_source != 'binance_client':
            text += f"\n(Nguồn dữ liệu: {fetch_source})"
        if args.dry_run_telegram:
            print("----- MESSAGE PREVIEW (dry-run) -----")
            print(text)
        else:
            tg_cfg = (cfg.get('telegram') or {})
            bot = TelegramBot(tg_cfg.get('bot_token'), tg_cfg.get('chat_id'), tg_cfg.get('parse_mode','Markdown'))
            bot.send_message(text)
            logger.info("Đã gửi kết quả quét lên Telegram.")


if __name__ == '__main__':
    main()
