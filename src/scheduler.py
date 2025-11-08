import logging
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone
import time
from typing import Dict, Any
from .fetcher import BinanceFetcher
from .indicators import compute_indicators, generate_signals, compute_ab, compute_weekly_ab
import pandas as pd
from .report import build_report
from .telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

class MarketReporter:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.fetcher = BinanceFetcher(config['binance']['symbols'], config['binance']['interval'])
        self.bot = TelegramBot(config['telegram'].get('bot_token'), config['telegram'].get('chat_id'), config['telegram'].get('parse_mode','Markdown'))
        self.scheduler = BackgroundScheduler(timezone=timezone.utc)
        testing = config.get('testing', {})
        self.quick_mode = bool(testing.get('quick_mode', False))
        self.fetch_limit = int(testing.get('fetch_limit', 300))

    def _prepare_df(self, symbol: str):
        raw = self.fetcher.get_klines(symbol, self.config['binance']['interval'], limit=self.fetch_limit)
        df = self.fetcher.to_dataframe(raw)
        # Merge indicator toggles (report) with parameters (indicators)
        merged = {**self.config['report'], **self.config['indicators']}
        if self.quick_mode:
            # Skip MACD in quick mode to accelerate
            merged['include_macd'] = False
        df_ind = compute_indicators(df, merged)
        return df_ind

    def periodic_report(self):
        for symbol in self.config['binance']['symbols']:
            df = self._prepare_df(symbol)
            signals = generate_signals(df, self.config['indicators'])
            # Include AB and AB_W values (if configured)
            custom_cfg = self.config.get('custom_signals', {}).get('abw_volume_spike', {})
            if custom_cfg.get('enabled'):
                try:
                    ab_series = compute_ab(df, int(custom_cfg.get('bb_length', 20)), float(custom_cfg.get('bb_mult', 2.0)))
                    ab_latest = float(ab_series.dropna().iloc[-1]) if not ab_series.dropna().empty else float('nan')
                    ab_w = compute_weekly_ab(
                        self.fetcher,
                        symbol,
                        custom_cfg.get('weekly_interval', '1w'),
                        int(custom_cfg.get('bb_length', 20)),
                        float(custom_cfg.get('bb_mult', 2.0)),
                        limit=60 if self.quick_mode else 120
                    )
                    signals['ab_values'] = f"AB={ab_latest:.2f}, AB_W={ab_w:.2f}"
                except Exception as e:
                    logger.exception("Error computing AB/AB_W values for %s: %s", symbol, e)
            text = build_report(symbol, df, signals, self.config['report']['decimals'])
            self.bot.send_message(text)

    def check_signals(self):
        for symbol in self.config['binance']['symbols']:
            df = self._prepare_df(symbol)
            signals = generate_signals(df, self.config['indicators'])
            # Custom: AB_W < threshold and Daily Volume spike > multiplier * MA
            custom_cfg = self.config.get('custom_signals', {}).get('abw_volume_spike', {})
            if custom_cfg.get('enabled'):
                try:
                    weekly_interval = custom_cfg.get('weekly_interval', '1w')
                    daily_interval = custom_cfg.get('daily_interval', '1d')
                    bb_length = int(custom_cfg.get('bb_length', 20))
                    bb_mult = float(custom_cfg.get('bb_mult', 2.0))
                    abw_lt = float(custom_cfg.get('abw_lt', 1.0))
                    vol_ma_len = int(custom_cfg.get('volume_ma_length', 20))
                    vol_mult = float(custom_cfg.get('volume_multiplier', 10.0))

                    # Weekly AB
                    ab_w = compute_weekly_ab(self.fetcher, symbol, weekly_interval, bb_length, bb_mult, limit=60)

                    # Daily volume series
                    daily_raw = self.fetcher.get_klines(symbol, daily_interval, limit=max(vol_ma_len + 2, 25))
                    daily_df = self.fetcher.to_dataframe(daily_raw)
                    if not daily_df.empty and daily_df['volume'].notna().sum() >= vol_ma_len + 1:
                        vol_ma = daily_df['volume'].rolling(vol_ma_len).mean().iloc[-1]
                        vol_latest = daily_df['volume'].iloc[-1]
                        if pd.notna(vol_ma) and pd.notna(vol_latest) and pd.notna(ab_w):
                            if (ab_w < abw_lt) and (vol_latest > vol_mult * vol_ma):
                                signals['abw_volume_spike'] = (
                                    f"AB_W={ab_w:.2f} < {abw_lt}, Volume {vol_latest:.0f} > {vol_mult}x MA{vol_ma_len} ({vol_ma:.0f})"
                                )
                except Exception as e:
                    logger.exception("Error evaluating custom ABW volume spike for %s: %s", symbol, e)
            if signals:
                text = build_report(symbol, df, signals, self.config['report']['decimals'])
                self.bot.send_message(text)

    def start(self):
        cron = self.config['scheduler']['report_cron'].split()
        if len(cron) != 5:
            raise ValueError("Cron expression must have 5 fields (min hour day month weekday)")
        self.scheduler.add_job(self.periodic_report, 'cron', minute=cron[0], hour=cron[1], day=cron[2], month=cron[3], day_of_week=cron[4], id='periodic_report')
        interval = self.config['scheduler']['check_interval_seconds']
        if self.quick_mode and interval > 15:
            # speed up checks in quick mode but keep safe lower bound
            interval = 15
        self.scheduler.add_job(self.check_signals, 'interval', seconds=interval, id='signal_check')
        self.scheduler.start()
        logger.info("Scheduler started.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping scheduler...")
            self.scheduler.shutdown()
