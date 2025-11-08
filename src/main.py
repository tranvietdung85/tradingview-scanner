import os
import yaml
import logging
import argparse
from dotenv import load_dotenv
from src.scheduler import MarketReporter

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')

def load_config(path: str = 'config.yaml'):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file {path} not found. Create it from config.example.yaml")
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Binance Telegram Reporter')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--quick', action='store_true', help='Enable quick mode (reduced indicators & candles)')
    parser.add_argument('--oneshot', action='store_true', help='Send one report then exit')
    args = parser.parse_args()

    config = load_config(args.config)
    # Override testing flags via CLI if provided
    testing = config.setdefault('testing', {})
    if args.quick:
        testing['quick_mode'] = True
    if args.oneshot:
        testing['oneshot'] = True
    reporter = MarketReporter(config)
    if testing.get('oneshot'):
        reporter.periodic_report()
        logging.info('One-shot report sent. Exiting.')
        return
    reporter.start()

if __name__ == '__main__':
    main()
