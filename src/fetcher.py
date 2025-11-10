from datetime import datetime, timezone
from binance.spot import Spot
import time
import logging
from typing import List, Dict, Any, Optional
import os
import requests

logger = logging.getLogger(__name__)

class BinanceFetcher:
    def __init__(self, symbols: List[str], interval: str):
        # Optional: allow proxy and base_url override via environment variables for CI/regions
        base_url = os.getenv('BINANCE_BASE_URL')
        proxy = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy') or os.getenv('HTTP_PROXY') or os.getenv('http_proxy') or os.getenv('PROXY_URL')
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        kwargs = {}
        if base_url:
            kwargs['base_url'] = base_url
        try:
            if proxies:
                kwargs['proxies'] = proxies
            self.client = Spot(**kwargs)
        except TypeError:
            # Some versions may not support 'proxies'; retry without it
            kwargs.pop('proxies', None)
            self.client = Spot(**kwargs)
        self.symbols = symbols
        self.interval = interval
        # Known Binance mirrors to try for REST calls when default fails
        mirrors_env = os.getenv('BINANCE_MIRRORS')  # comma-separated
        if mirrors_env:
            self.mirror_urls = [u.strip() for u in mirrors_env.split(',') if u.strip()]
        else:
            self.mirror_urls = [
                os.getenv('BINANCE_BASE_URL') or 'https://api.binance.com',
                'https://api1.binance.com',
                'https://api3.binance.com',
                'https://api-gcp.binance.com'
            ]
        self.requests_session = requests.Session()
        if proxies:
            self.requests_session.proxies.update(proxies)
        self.last_source: Optional[str] = None  # 'binance_client' | 'binance_http' | 'yfinance'

    def get_price(self, symbol: str) -> float:
        try:
            data = self.client.ticker_price(symbol)
            self.last_source = 'binance_client'
            return float(data['price'])
        except Exception:
            # fallback to HTTP REST
            for base in self.mirror_urls:
                try:
                    url = f"{base}/api/v3/ticker/price"
                    r = self.requests_session.get(url, params={'symbol': symbol}, timeout=10)
                    if r.status_code == 200:
                        self.last_source = 'binance_http'
                        return float(r.json()['price'])
                except Exception:
                    continue
            raise

    def get_klines(self, symbol: str, interval: str = None, limit: int = 200) -> List[List[Any]]:
        interval = interval or self.interval
        # 1) Try official client first
        try:
            data = self.client.klines(symbol, interval, limit=limit)
            self.last_source = 'binance_client'
            return data
        except Exception as e:
            msg = str(e).lower()
            # If region restricted or other failures, try HTTP mirrors
            http_data = self._try_http_klines(symbol, interval, limit)
            if http_data is not None:
                self.last_source = 'binance_http'
                return http_data
            # Last resort: yfinance (maps XXXUSDT -> XXX-USD). May not cover all pairs/timeframes
            yf_data = self._try_yfinance_klines(symbol, interval, limit)
            if yf_data is not None:
                self.last_source = 'yfinance'
                return yf_data
            raise

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

    def _try_http_klines(self, symbol: str, interval: str, limit: int) -> Optional[List[List[Any]]]:
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        for base in self.mirror_urls:
            try:
                url = f"{base}/api/v3/klines"
                r = self.requests_session.get(url, params=params, timeout=15)
                if r.status_code == 200:
                    return r.json()
                # Continue trying other mirrors on 4xx/5xx
            except Exception:
                continue
        return None

    @staticmethod
    def _map_symbol_to_yf(symbol: str) -> Optional[str]:
        # Map 'BTCUSDT' -> 'BTC-USD'; simple heuristic for USDT pairs; skip leveraged tokens
        if not symbol.endswith('USDT'):
            return None
        base = symbol[:-4]
        # Filter out leveraged suffixes
        for suf in ('UP', 'DOWN', '3L', '3S'):
            if base.endswith(suf):
                return None
        return f"{base}-USD"

    def _try_yfinance_klines(self, symbol: str, interval: str, limit: int) -> Optional[List[List[Any]]]:
        try:
            import yfinance as yf
        except Exception:
            return None
        yf_symbol = self._map_symbol_to_yf(symbol)
        if not yf_symbol:
            return None
        # Map interval
        yf_interval = interval
        if interval == '1w':
            yf_interval = '1wk'
        # yfinance requires a period; pick a reasonable period to cover 'limit' bars
        period = self._infer_yf_period(yf_interval, limit)
        try:
            df = yf.download(yf_symbol, interval=yf_interval, period=period, auto_adjust=False, progress=False)
            if df is None or df.empty:
                return None
            df = df.tz_convert('UTC') if df.index.tz is not None else df.tz_localize('UTC')
            # Build Binance-like kline rows
            rows: List[List[Any]] = []
            for ts, row in df.tail(limit).iterrows():
                open_time_ms = int(ts.timestamp() * 1000)
                # Estimate close_time as next bar open - 1ms; fall back to open_time
                close_time_ms = open_time_ms
                rows.append([
                    open_time_ms,
                    float(row['Open']),
                    float(row['High']),
                    float(row['Low']),
                    float(row['Close']),
                    float(row.get('Volume', 0.0) or 0.0),
                    close_time_ms,
                    0.0,  # quote_volume unknown
                    0,    # trades unknown
                    0.0,  # taker_buy_base
                    0.0,  # taker_buy_quote
                    0
                ])
            return rows
        except Exception:
            return None

    @staticmethod
    def _infer_yf_period(yf_interval: str, limit: int) -> str:
        # Choose a period that can cover 'limit' bars comfortably
        if yf_interval in ('1m','2m','5m','15m','30m'):
            days = max(1, int(limit / 48) + 1)
            return f"{days}d"
        if yf_interval in ('60m','90m','1h'):
            days = max(7, int(limit / 24) + 2)
            return f"{days}d"
        if yf_interval in ('1d','5d'):
            days = max(30, limit + 5)
            return f"{days}d"
        if yf_interval in ('1wk',):
            weeks = max(60, limit + 5)
            months = int(weeks / 4) + 1
            return f"{months}mo"
        if yf_interval in ('1mo','3mo'):
            months = max(24, limit + 2)
            return f"{months}mo"
        return '2y'

    def fetch_ticker_24hr(self) -> Optional[List[Dict[str, Any]]]:
        # Try client first
        try:
            data = self.client.ticker_24hr()
            self.last_source = 'binance_client'
            return data
        except Exception:
            # Try HTTP mirrors
            for base in self.mirror_urls:
                try:
                    url = f"{base}/api/v3/ticker/24hr"
                    r = self.requests_session.get(url, timeout=15)
                    if r.status_code == 200:
                        self.last_source = 'binance_http'
                        return r.json()
                except Exception:
                    continue
        return None
