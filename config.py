import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '').strip()
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'openrouter/free').strip()
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek/deepseek-chat-v3.1:free').strip()
OPENROUTER_EDITOR_MODEL = os.getenv('OPENROUTER_EDITOR_MODEL', 'openai/gpt-oss-120b:free').strip()
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
RSS_SOURCES = [x.strip() for x in os.getenv('RSS_SOURCES', 'https://www.motor1.com/rss/,https://news.drom.ru/rss/').split(',') if x.strip()]

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
    if not OPENROUTER_API_KEY: errors.append('OPENROUTER_API_KEY не задан')
    if ARTICLES_PER_DAY * 5 > OPENROUTER_DAILY_LIMIT: errors.append('OPENROUTER_DAILY_LIMIT мал для основной AI-цепочки и ремонта качества')
    if MIN_ARTICLE_WORDS >= MAX_ARTICLE_WORDS: errors.append('MIN_ARTICLE_WORDS должен быть меньше MAX_ARTICLE_WORDS')
    if not SCHEDULE_HOURS: errors.append('SCHEDULE_HOURS пуст')
    if bool(YANDEX_API_KEY) != bool(YANDEX_FOLDER_ID): errors.append('Для Yandex AI нужны одновременно YANDEX_API_KEY и YANDEX_FOLDER_ID')
    return errors
