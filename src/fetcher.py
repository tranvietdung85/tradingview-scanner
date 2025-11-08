from datetime import datetime, timezone
from binance.spot import Spot
import time
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class BinanceFetcher:
    def __init__(self, symbols: List[str], interval: str):
        self.client = Spot()
        self.symbols = symbols
        self.interval = interval

    def get_price(self, symbol: str) -> float:
        data = self.client.ticker_price(symbol)
        return float(data['price'])

    def get_klines(self, symbol: str, interval: str = None, limit: int = 200) -> List[List[Any]]:
        interval = interval or self.interval
        return self.client.klines(symbol, interval, limit=limit)

    def get_klines_between(self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1000) -> List[List[Any]]:
        all_rows = []
        cursor = start_ms
        while True:
            batch = self.client.klines(symbol, interval, startTime=cursor, endTime=end_ms, limit=limit)
            if not batch:
                break
            all_rows.extend(batch)
            last_close = batch[-1][6]
            if last_close >= end_ms or len(batch) < limit:
                break
            cursor = last_close + 1
            time.sleep(0.2)
        return all_rows

    @staticmethod
    def to_dataframe(raw: List[List[Any]]):
        import pandas as pd
        if not raw:
            return pd.DataFrame(columns=["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"])
        cols = ["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]
        df = pd.DataFrame(raw, columns=cols)
        numeric = ["open","high","low","close","volume"]
        df[numeric] = df[numeric].astype(float)
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)
        df = df.set_index('open_time').sort_index()
        return df
