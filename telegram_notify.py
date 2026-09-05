import json
from pathlib import Path

import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _require_telegram():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError('TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не настроены')


def _send(text):
    _require_telegram()
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
    """Send the full publication-grade article and return sent message ids."""
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


def notify_image_set(preview_path, *, headline: str, batch_id: int, attempt: int):
    """Send one contact-sheet preview and one decision pair for all five images."""
    _require_telegram()
    path = Path(preview_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    keyboard = {
        'inline_keyboard': [[
            {'text': '✅ Набор ок', 'callback_data': f'imageset_ok:{batch_id}'},
            {'text': '♻️ Перегенерировать набор', 'callback_data': f'imageset_regen:{batch_id}'},
        ]]
    }
    caption = (
        f'🖼 Набор изображений #{batch_id} · попытка {attempt}\n\n'
        f'{headline}\n\n'
        'Проверь пять кадров как единый набор.'
    )
    with path.open('rb') as fh:
        response = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto',
            data={
                'chat_id': TELEGRAM_CHAT_ID,
                'caption': caption[:1024],
                'reply_markup': json.dumps(keyboard, ensure_ascii=False),
            },
            files={'photo': (path.name, fh, 'image/jpeg')},
            timeout=60,
        )
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError('Telegram sendPhoto ok=false: ' + str(data.get('description', 'unknown error')))
    message_id = (data.get('result') or {}).get('message_id')
    print(f'TELEGRAM_IMAGE_SET_OK batch_id={batch_id} message_id={message_id}')
    return message_id


def send_document(path, caption=''):
    """Send a finished ZIP/DOCX file to the configured Telegram chat."""
    _require_telegram()
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(str(file_path))
    with file_path.open('rb') as fh:
        response = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument',
            data={'chat_id': TELEGRAM_CHAT_ID, 'caption': (caption or '')[:1024]},
            files={'document': (file_path.name, fh, 'application/zip')},
            timeout=120,
        )
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError('Telegram sendDocument ok=false: ' + str(data.get('description', 'unknown error')))
    message_id = (data.get('result') or {}).get('message_id')
    print(f'TELEGRAM_DOCUMENT_OK file={file_path.name} message_id={message_id}')
    return message_id
