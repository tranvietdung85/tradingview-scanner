import logging
import argparse
import math
import os
import yaml
from datetime import datetime, timezone, timedelta
from typing import Dict, List
import pandas as pd
from binance.spot import Spot

from src.fetcher import BinanceFetcher
from src.indicators import compute_weekly_ab

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def load_config(path: str = 'config.yaml') -> Dict:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def list_top_usdt_symbols(client: Spot, top_n: int = 50) -> List[str]:
    tickers = client.ticker_24hr()
    pairs = []
    for t in tickers:
        sym = t.get('symbol')
        if not sym or not sym.endswith('USDT'):
            continue
        if any(x in sym for x in ['UP', 'DOWN', '3L', '3S']):
            continue
        try:
            qv = float(t.get('quoteVolume', 0.0))
        except ValueError:
            qv = 0.0
        pairs.append((sym, qv))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in pairs[:top_n]]


def get_daily_df(fetcher: BinanceFetcher, symbol: str, days: int) -> pd.DataFrame:
    # Fetch slightly more candles than needed (days + buffer) due to missing early bars and MA windows
    raw = fetcher.get_klines(symbol, '1d', limit=days + 40)
    df = fetcher.to_dataframe(raw)
    return df.tail(days + 5)  # keep last N+5 to ensure moving averages are valid


def prepare_weekly_ab(fetcher: BinanceFetcher, symbol: str, weekly_len: int, weekly_mult: float) -> pd.Series:
    raw = fetcher.get_klines(symbol, '1w', limit=weekly_len + 80)
    wdf = fetcher.to_dataframe(raw)
    if wdf.empty:
        return pd.Series(dtype=float)
    # Compute AB_W series over weekly dataframe
    from src.indicators import compute_ab
    ab_series = compute_ab(wdf, weekly_len, weekly_mult)
    # Shift one to avoid lookahead (use completed week value for following days)
    ab_series_shifted = ab_series.shift(1)
    ab_series_shifted.name = 'ab_w'
    # Map weekly to daily index by forward filling to next weekly close
    return ab_series_shifted


def map_weekly_to_daily(daily_index: pd.DatetimeIndex, weekly_series: pd.Series) -> pd.Series:
    # Reindex with forward fill
    return weekly_series.reindex(daily_index, method='ffill')


def find_signals_for_symbol(fetcher: BinanceFetcher, symbol: str, days: int, abw_lt: float, vol_ma_len: int, vol_mult: float, weekly_len: int, weekly_mult: float) -> pd.DataFrame:
    daily_df = get_daily_df(fetcher, symbol, days)
    if daily_df.empty:
        return pd.DataFrame(columns=['symbol','date','ab_w','volume','vol_ma'])

    # Prepare weekly AB_W shifted (no lookahead)
    weekly_ab = prepare_weekly_ab(fetcher, symbol, weekly_len, weekly_mult)
    ab_w_daily = map_weekly_to_daily(daily_df.index, weekly_ab)
    daily_df['ab_w'] = ab_w_daily

    # Volume MA (exclude current day for spike check by shifting MA)
    daily_df['vol_ma'] = daily_df['volume'].rolling(vol_ma_len).mean().shift(1)

    cond = (
        (daily_df['ab_w'] < abw_lt) &
        (daily_df['volume'] > vol_mult * daily_df['vol_ma'])
    )
    hits = daily_df[cond].copy()
    if hits.empty:
        return pd.DataFrame(columns=['symbol','date','ab_w','volume','vol_ma'])
    hits['symbol'] = symbol
    hits['date'] = hits.index
    return hits[['symbol','date','ab_w','volume','vol_ma']]


def scan_history(top_n: int, days: int, abw_lt: float, vol_ma_len: int, vol_mult: float, weekly_len: int, weekly_mult: float) -> pd.DataFrame:
    client = Spot()
    fetcher = BinanceFetcher([], '1d')
    symbols = list_top_usdt_symbols(client, top_n=top_n)
    logger.info("Historical scan %d days for %d symbols...", days, len(symbols))
    all_hits = []
    for sym in symbols:
        try:
            hits = find_signals_for_symbol(fetcher, sym, days, abw_lt, vol_ma_len, vol_mult, weekly_len, weekly_mult)
            if not hits.empty:
                logger.info("%s: %d hits", sym, len(hits))
                all_hits.append(hits)
        except Exception as e:
            logger.exception("Error processing %s: %s", sym, e)
    if not all_hits:
        return pd.DataFrame(columns=['symbol','date','ab_w','volume','vol_ma'])
    return pd.concat(all_hits).sort_values(by='date')


def main():
    parser = argparse.ArgumentParser(description='Historical scan for AB_W + Volume spike condition')
    parser.add_argument('--top', type=int, default=50, help='Top-N USDT pairs by 24h volume')
    parser.add_argument('--days', type=int, default=50, help='Number of past daily candles to evaluate')
    parser.add_argument('--abw-lt', type=float, default=1.2, help='AB_W must be below this threshold')
    parser.add_argument('--vol-ma-len', type=int, default=20, help='Volume MA length')
    parser.add_argument('--vol-mult', type=float, default=5.0, help='Volume multiplier over MA')
    parser.add_argument('--bb-len', type=int, default=20, help='Weekly Bollinger length')
    parser.add_argument('--bb-mult', type=float, default=2.0, help='Weekly Bollinger multiplier')
    parser.add_argument('--out-csv', type=str, default='', help='Save hits to CSV file path')
    args = parser.parse_args()

    cfg = load_config()
    cs = (cfg.get('custom_signals') or {}).get('abw_volume_spike') or {}
    abw_lt = float(cs.get('abw_lt', args.abw_lt))
    vol_ma_len = int(cs.get('volume_ma_length', args.vol_ma_len))
    vol_mult = float(cs.get('volume_multiplier', args.vol_mult))
    weekly_len = int(cs.get('bb_length', args.bb_len))
    weekly_mult = float(cs.get('bb_mult', args.bb_mult))

    result = scan_history(
        top_n=args.top,
        days=args.days,
        abw_lt=abw_lt,
        vol_ma_len=vol_ma_len,
        vol_mult=vol_mult,
        weekly_len=weekly_len,
        weekly_mult=weekly_mult
    )

    if result.empty:
        logger.info("No historical hits found for given parameters.")
    else:
        print("\nHistorical matches:")
        print(result.to_string(index=False))
        if args.out_csv:
            result.to_csv(args.out_csv, index=False)
            logger.info("Saved to %s", args.out_csv)

if __name__ == '__main__':
    main()
