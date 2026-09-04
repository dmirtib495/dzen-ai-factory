import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return
    requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': text[:4096], 'disable_web_page_preview': True},
        timeout=20,
    ).raise_for_status()


def notify(text):
    try:
        _send(text)
    except Exception as e:
        print('Telegram:', e)


def notify_article(header, article_markdown):
    """Send a publication-grade article itself, split safely for Telegram."""
    try:
        _send(header)
        text = (article_markdown or '').strip()
        while text:
            if len(text) <= 3900:
                chunk, text = text, ''
            else:
                cut = text.rfind('\n\n', 0, 3900)
                if cut < 1000:
                    cut = text.rfind('\n', 0, 3900)
                if cut < 1000:
                    cut = 3900
                chunk, text = text[:cut].strip(), text[cut:].strip()
            if chunk:
                _send(chunk)
    except Exception as e:
        print('Telegram article:', e)
