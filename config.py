import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '').strip()
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'openrouter/free').strip()
# The former DeepSeek :free slug was retired. Keep the variable name for
# backward compatibility, but default to a concrete currently-free model that
# advertises response_format/structured output support. openrouter/free stays
# the final reserve inside ai_writer.py.
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'google/gemma-4-31b-it:free').strip()
# Prefer a larger concrete free model for editing/audit/repair. The workflow
# preflight verifies this slug is still free before production generation.
OPENROUTER_EDITOR_MODEL = os.getenv('OPENROUTER_EDITOR_MODEL', 'nvidia/nemotron-3-super-120b-a12b:free').strip()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5-mini').strip()
YANDEX_API_KEY = os.getenv('YANDEX_API_KEY', '').strip()
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', '').strip()
YANDEX_MODEL = os.getenv('YANDEX_MODEL', 'yandexgpt/latest').strip()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
ARTICLES_PER_DAY = max(1, int(os.getenv('ARTICLES_PER_DAY', '3')))
OPENROUTER_DAILY_LIMIT = max(1, int(os.getenv('OPENROUTER_DAILY_LIMIT', '50')))
TIMEZONE = os.getenv('TIMEZONE', 'Europe/Moscow').strip()
CHANNEL_NAME = 'Авто без переплаты'
MIN_ARTICLE_WORDS = int(os.getenv('MIN_ARTICLE_WORDS', '900'))
MAX_ARTICLE_WORDS = int(os.getenv('MAX_ARTICLE_WORDS', '1400'))
SCHEDULE_HOURS = tuple(int(x) for x in os.getenv('SCHEDULE_HOURS', '6,12,18').split(',') if x.strip())
RSS_SOURCES = [x.strip() for x in os.getenv(
    'RSS_SOURCES',
    'https://www.drom.ru/export/xml/news.rss,https://www.drom.ru/export/xml/reviews.rss'
).split(',') if x.strip()]

DB_PATH = DATA_DIR / 'factory.db'
LOCK_PATH = DATA_DIR / 'factory.lock'
LOG_DIR = DATA_DIR / 'logs'
BACKUP_DIR = DATA_DIR / 'backups'
OUTBOX_DIR = DATA_DIR / 'publish_outbox'
APPROVED_DIR = DATA_DIR / 'approved'
REJECTED_DIR = DATA_DIR / 'rejected'
ARTICLES_DIR = DATA_DIR / 'articles'
for p in (LOG_DIR, BACKUP_DIR, OUTBOX_DIR, APPROVED_DIR, REJECTED_DIR, ARTICLES_DIR):
    p.mkdir(parents=True, exist_ok=True)


def validate():
    errors = []
    if not OPENROUTER_API_KEY:
        errors.append('OPENROUTER_API_KEY не задан')
    if not YANDEX_API_KEY:
        errors.append('YANDEX_API_KEY не задан: YandexGPT — обязательный редакционный этап')
    if not YANDEX_FOLDER_ID:
        errors.append('YANDEX_FOLDER_ID не задан: YandexGPT — обязательный редакционный этап')
    if ARTICLES_PER_DAY * 5 > OPENROUTER_DAILY_LIMIT:
        errors.append('OPENROUTER_DAILY_LIMIT мал для основной AI-цепочки и ремонта качества')
    if MIN_ARTICLE_WORDS >= MAX_ARTICLE_WORDS:
        errors.append('MIN_ARTICLE_WORDS должен быть меньше MAX_ARTICLE_WORDS')
    if not SCHEDULE_HOURS:
        errors.append('SCHEDULE_HOURS пуст')
    return errors
