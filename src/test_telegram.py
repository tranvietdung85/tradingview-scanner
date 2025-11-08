import yaml
import os
import logging
from dotenv import load_dotenv
from src.telegram_bot import TelegramBot

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')

def load_config(path: str = 'config.yaml'):
    if not os.path.exists(path):
        raise FileNotFoundError("config.yaml not found")
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def ensure_tokens(cfg):
    """Ensure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are available via env.
    If missing, try from config; if still missing, prompt user and write to .env.
    """
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if bot_token and chat_id:
        return
    tg_cfg = cfg.get('telegram', {}) if isinstance(cfg, dict) else {}
    bot_token = bot_token or tg_cfg.get('bot_token') or ''
    chat_id = chat_id or tg_cfg.get('chat_id') or ''
    if bot_token and chat_id:
        os.environ['TELEGRAM_BOT_TOKEN'] = bot_token
        os.environ['TELEGRAM_CHAT_ID'] = chat_id
        return
    # Prompt user to enter once and store to .env
    print("Telegram credentials not found. Enter them to create/update .env (kept locally):")
    bot_token = input("BOT TOKEN: ").strip()
    chat_id = input("CHAT ID: ").strip()
    if not bot_token or not chat_id:
        raise ValueError("Missing token or chat id. Aborting.")
    # Append or create .env
    lines = [f"TELEGRAM_BOT_TOKEN={bot_token}\n", f"TELEGRAM_CHAT_ID={chat_id}\n"]
    try:
        with open('.env', 'a', encoding='utf-8') as f:
            for line in lines:
                f.write(line)
        # Reload
        load_dotenv(override=True)
    except Exception as e:
        print(f"Failed to write .env: {e}")
        os.environ['TELEGRAM_BOT_TOKEN'] = bot_token
        os.environ['TELEGRAM_CHAT_ID'] = chat_id


def main():
    # Load environment variables from .env if present
    load_dotenv()
    cfg = load_config()
    ensure_tokens(cfg)
    tg_cfg = cfg.get('telegram', {})
    bot = TelegramBot(tg_cfg.get('bot_token'), tg_cfg.get('chat_id'), tg_cfg.get('parse_mode','Markdown'))
    resp = bot.send_message("Test message from tradingview project ✅")
    print(resp)

if __name__ == '__main__':
    main()
