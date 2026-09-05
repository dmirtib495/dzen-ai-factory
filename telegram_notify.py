import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError('TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не настроены')
    response = requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': text[:4096], 'disable_web_page_preview': True},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError('Telegram API вернул ok=false: ' + str(data.get('description', 'unknown error')))
    message_id = (data.get('result') or {}).get('message_id')
    print(f'TELEGRAM_SEND_OK message_id={message_id}')
    return message_id


def notify(text):
    try:
        return _send(text)
    except Exception as e:
        print('Telegram:', e)
        return None


def notify_article(header, article_markdown):
    """Send the full publication-grade article and return sent message ids.

    Delivery is considered successful only when every Telegram API call returns
    HTTP success and ok=true. The caller can then distinguish generated from
    actually delivered articles.
    """
    sent = []
    sent.append(_send(header))
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
            sent.append(_send(chunk))
    print(f'TELEGRAM_ARTICLE_DELIVERED messages={sent}')
    return sent
