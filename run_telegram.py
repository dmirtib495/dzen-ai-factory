from logging_setup import setup_logging
from telegram_control import ControlBot
setup_logging(); ControlBot().loop()
