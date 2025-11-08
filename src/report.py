from typing import Dict, Any
import pandas as pd

def build_report(symbol: str, df: pd.DataFrame, signals: Dict[str, Any], decimals: int = 2) -> str:
    last = df.iloc[-1]
    price = last['close']
    lines = [f"*Report:* `{symbol}`", f"Last Close: `{price:.{decimals}f}`"]
    if 'rsi' in last:
        lines.append(f"RSI: `{last['rsi']:.2f}`")
    if 'ema_fast' in last and 'ema_slow' in last:
        lines.append(f"EMA Fast/Slow: `{last['ema_fast']:.2f}` / `{last['ema_slow']:.2f}`")
    if 'macd' in last and 'signal' in last and 'hist' in last:
        lines.append(f"MACD: `{last['macd']:.2f}` Signal: `{last['signal']:.2f}` Hist: `{last['hist']:.2f}`")
    if signals:
        lines.append("\n*Signals:*")
        for k, v in signals.items():
            lines.append(f"- {v}")
    else:
        lines.append("\n_No new signals_.")
    return "\n".join(lines)
