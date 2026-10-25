"""cPanel/Passenger entry point; analyses are processed by the separate cron worker."""

from pathlib import Path

from dotenv import load_dotenv

from tradingagents.web.app import create_app

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
application = create_app()
