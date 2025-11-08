import pandas as pd
import numpy as np
from typing import Dict, Any

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    gain_rol = pd.Series(gain, index=series.index).rolling(window=period).mean()
    loss_rol = pd.Series(loss, index=series.index).rolling(window=period).mean()
    rs = gain_rol / loss_rol
    rsi = 100 - (100 / (1 + rs))
    return rsi

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})

def bollinger(series: pd.Series, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    ma = series.rolling(length).mean()
    std = series.rolling(length).std(ddof=0)
    upper = ma + mult * std
    lower = ma - mult * std
    return pd.DataFrame({"bb_middle": ma, "bb_upper": upper, "bb_lower": lower, "bb_std": std})

def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df['close'].shift(1)
    hi_lo = df['high'] - df['low']
    hi_pc = (df['high'] - prev_close).abs()
    lo_pc = (df['low'] - prev_close).abs()
    tr = pd.concat([hi_lo, hi_pc, lo_pc], axis=1).max(axis=1)
    return tr

def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return true_range(df).rolling(length).mean()

def bb_atr_signal(df: pd.DataFrame, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """Compute Bollinger components and the ratio (upper-middle)/(middle-lower)."""
    bb = bollinger(df['close'], length, mult)
    out = df.join(bb)
    # (upper - middle) and (middle - lower)
    up_mid = out['bb_upper'] - out['bb_middle']
    mid_low = out['bb_middle'] - out['bb_lower']
    ratio = up_mid / mid_low
    out['bb_symmetry_ratio'] = ratio
    out['bb_halfband'] = up_mid
    out['atr'] = atr(out, length)
    out['bb_halfband_over_atr'] = out['bb_halfband'] / out['atr']
    return out

def compute_ab(df: pd.DataFrame, length: int = 20, mult: float = 2.0) -> pd.Series:
    bb = bollinger(df['close'], length, mult)
    halfband = bb['bb_upper'] - bb['bb_middle']  # == mult * std
    tr_atr = atr(df, length)
    return (halfband / tr_atr).rename('ab')

def compute_weekly_ab(fetcher, symbol: str, weekly_interval: str, length: int = 20, mult: float = 2.0, limit: int = 100) -> float:
    """Fetch weekly klines and compute latest AB_W value."""
    raw = fetcher.get_klines(symbol, weekly_interval, limit=limit)
    wdf = fetcher.to_dataframe(raw)
    if wdf.empty:
        return float('nan')
    ab_series = compute_ab(wdf, length, mult)
    return float(ab_series.dropna().iloc[-1]) if not ab_series.dropna().empty else float('nan')

def compute_indicators(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    price = out['close']
    if config.get('include_ema'):
        out['ema_fast'] = ema(price, config['ema']['fast'])
        out['ema_slow'] = ema(price, config['ema']['slow'])
    if config.get('include_rsi'):
        out['rsi'] = rsi(price, config['rsi']['period'])
    if config.get('include_macd'):
        m = macd(price, config['macd']['fast'], config['macd']['slow'], config['macd']['signal'])
        out = out.join(m)
    return out

def generate_signals(df: pd.DataFrame, config: Dict[str, Any]) -> Dict[str, Any]:
    signals = {}
    if 'rsi' in df.columns:
        latest_rsi = df['rsi'].iloc[-1]
        if latest_rsi >= config['rsi']['overbought']:
            signals['rsi'] = f"RSI overbought ({latest_rsi:.2f})"
        elif latest_rsi <= config['rsi']['oversold']:
            signals['rsi'] = f"RSI oversold ({latest_rsi:.2f})"
    if 'ema_fast' in df.columns and 'ema_slow' in df.columns:
        if df['ema_fast'].iloc[-1] > df['ema_slow'].iloc[-1] and df['ema_fast'].iloc[-2] <= df['ema_slow'].iloc[-2]:
            signals['ema_cross'] = "Bullish EMA crossover"
        elif df['ema_fast'].iloc[-1] < df['ema_slow'].iloc[-1] and df['ema_fast'].iloc[-2] >= df['ema_slow'].iloc[-2]:
            signals['ema_cross'] = "Bearish EMA crossover"
    if 'macd' in df.columns and 'signal' in df.columns:
        if df['macd'].iloc[-1] > df['signal'].iloc[-1] and df['macd'].iloc[-2] <= df['signal'].iloc[-2]:
            signals['macd_cross'] = "MACD bullish cross"
        elif df['macd'].iloc[-1] < df['signal'].iloc[-1] and df['macd'].iloc[-2] >= df['signal'].iloc[-2]:
            signals['macd_cross'] = "MACD bearish cross"
    return signals
