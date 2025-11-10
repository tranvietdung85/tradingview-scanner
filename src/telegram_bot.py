import os
import re
import requests
import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None, parse_mode: str = "Markdown", dry_run: bool = False):
        self.token = token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.parse_mode = parse_mode
        self.dry_run = dry_run or os.getenv('TELEGRAM_DRY_RUN') == '1'
        if not self.dry_run and (not self.token or not self.chat_id):
            raise ValueError("Telegram token or chat id missing. Set in config or environment variables, or enable dry_run.")
        if not self.dry_run:
            self._preflight()

    def _valid_token_format(self) -> bool:
        # Rough pattern: digits, colon, long token part
        return bool(self.token and re.match(r"^\d{6,}:[A-Za-z0-9_-]{20,}$", self.token))

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _preflight(self):
        # Validate token format quickly
        if not self._valid_token_format():
            logging.warning("Telegram token format looks unusual. Double-check you copied it correctly from @BotFather.")
        # Call getMe to verify token
        try:
            r = requests.get(self._api_url('getMe'), timeout=10)
            if r.status_code == 200 and r.json().get('ok'):
                me = r.json().get('result', {})
                logging.info("Telegram bot authenticated: @%s (id=%s)", me.get('username'), me.get('id'))
            else:
                logging.error("Telegram getMe failed: %s - %s", r.status_code, r.text)
        except requests.RequestException as e:
            logging.exception("Telegram preflight getMe error: %s", e)
        # Optionally validate chat id
        if self.chat_id:
            try:
                r = requests.get(self._api_url('getChat'), params={'chat_id': self.chat_id}, timeout=10)
                if r.status_code != 200:
                    logging.warning("Telegram getChat warning: %s - %s", r.status_code, r.text)
                    logging.warning("If this is a private chat, ensure you've started the bot (click Start) to allow messages. For groups, add the bot and use the group chat_id (usually negative).")
                else:
                    res = r.json()
                    if res.get('ok'):
                        logging.info("Telegram chat recognized: %s", res['result'].get('title') or res['result'].get('username') or self.chat_id)
                    else:
                        logging.warning("Telegram getChat returned not ok: %s", r.text)
            except requests.RequestException as e:
                logging.exception("Telegram preflight getChat error: %s", e)

    def _request_with_retry(self, method: str, payload: dict, retries: int = 3, base_delay: float = 2.0) -> Tuple[Optional[requests.Response], Optional[Exception]]:
        """Send POST request with simple exponential backoff on timeout/connect errors."""
        url = self._api_url(method)
        attempt = 0
        while attempt <= retries:
            try:
                r = requests.post(url, json=payload, timeout=10)
                return r, None
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt == retries:
                    return None, e
                sleep_for = base_delay * (2 ** attempt)
                logging.warning("Telegram %s attempt %d failed (%s). Retrying in %.1fs", method, attempt+1, e.__class__.__name__, sleep_for)
                time.sleep(sleep_for)
            except requests.RequestException as e:
                return None, e
            attempt += 1
        return None, None

    def send_message(self, text: str, disable_web_page_preview: bool = True):
        # Basic escape for Markdown (not MarkdownV2) to avoid 'can't parse entities'
        if self.parse_mode == 'Markdown':
            # Escape underscores not inside code spans.
            def _escape(md: str) -> str:
                # Naive split on backticks to keep code blocks intact
                parts = md.split('`')
                for i in range(0, len(parts), 2):  # even indices are outside code spans
                    parts[i] = parts[i].replace('_', '\\_')
                return '`'.join(parts)
            text = _escape(text)
        if self.dry_run:
            logger.info("[DRY-RUN] Telegram message:\n%s", text)
            return {"ok": True, "dry_run": True}
        method = 'sendMessage'
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': self.parse_mode,
            'disable_web_page_preview': disable_web_page_preview
        }
        r, err = self._request_with_retry(method, payload)
        if err is not None or r is None:
            logger.error("Telegram send failed after retries: %s", err)
            return None
        if r.status_code != 200:
            logger.error("Telegram send failed: %s - %s", r.status_code, r.text)
            if r.status_code == 404:
                logger.error("Hint: 404 usually indicates an invalid bot token or wrong API path. Verify BOT_TOKEN from @BotFather and ensure method name is 'sendMessage'.")
            elif r.status_code == 400 and 'chat not found' in r.text.lower():
                logger.error("Hint: Chat ID invalid or the bot hasn't been started. Send a message to your bot first and use getUpdates to obtain chat_id.")
        else:
            logger.info("Telegram message delivered (status %s).", r.status_code)
        return r.json() if r is not None else None
