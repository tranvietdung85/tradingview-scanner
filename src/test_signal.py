import logging
from binance.spot import Spot
import pandas as pd
from datetime import datetime, timezone, timedelta
from src.indicators import bb_atr_signal

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')

symbol = 'BTCUSDT'
interval = '1h'
length = 20
mult = 2.0
limit = 250

client = Spot()
raw = client.klines(symbol, interval, limit=limit)
cols = ["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]

df = pd.DataFrame(raw, columns=cols)
for c in ["open","high","low","close","volume"]:
    df[c] = df[c].astype(float)

df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)

df = df.set_index('open_time').sort_index()

sig_df = bb_atr_signal(df, length=length, mult=mult)

last_rows = sig_df.tail(5)[['bb_upper','bb_middle','bb_lower','bb_symmetry_ratio','bb_halfband','atr','bb_halfband_over_atr']]
print("Last 5 rows (key fields):")
print(last_rows)

valid_ratio = sig_df['bb_symmetry_ratio'].dropna()
print('\nRatio unique values count:', valid_ratio.nunique())
print('Ratio min:', valid_ratio.min())
print('Ratio max:', valid_ratio.max())
print('All equal to 1? ->', bool((valid_ratio == 1).all()))
