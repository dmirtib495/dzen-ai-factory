from pathlib import Path
from datetime import datetime
import json, os, uuid
from config import ARTICLES_DIR, OUTBOX_DIR

QUEUE = ARTICLES_DIR
OUTBOX = OUTBOX_DIR


def _as_text(value):
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _bullet_lines(values, fallback):
    if not isinstance(values, list):
        values = [values] if values else []
    lines = [f'- {_as_text(item)}' for item in values if _as_text(item)]
    return '\n'.join(lines) or fallback


def save_to_queue(data, image_path=''):
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:6]
    p = QUEUE / (stamp + '.md')

    checks = _bullet_lines(
        data.get('fact_check', []),
        '- Нет отдельных пунктов',
    )
    sources = _bullet_lines(
        data.get('source_urls', []),
        '- Источник темы указан в метаданных; проверить перед публикацией.',
    )

    article_markdown = _as_text(data.get('article_markdown', ''))
    headline = _as_text(data.get('headline', ''))

    text = f'''# {headline}\n\n{article_markdown}\n\n## Что проверить перед публикацией\n{checks}\n\n## Источники\n{sources}\n\n## Изображение\n{image_path}\n'''
    p.write_text(text, encoding='utf-8')

    manifest = {
        'headline': headline,
        'category': _as_text(data.get('category', '')),
        'article_markdown': article_markdown,
        'source_urls': data.get('source_urls', []),
        'fact_check': data.get('fact_check', []),
        'image_path': str(image_path),
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'status': 'queued',
    }
    (OUTBOX / (stamp + '.json')).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return p


def publish(path):
    endpoint = os.getenv('ZEN_PUBLISH_ENDPOINT', '').strip()
    if not endpoint:
        raise RuntimeError(
            'Публикация не настроена: материал оставлен в outbox для ручной публикации через поддерживаемый интерфейс Дзена.'
        )
    raise RuntimeError(
        'Автоматическая публикация не включена: универсальный официальный API-контракт не подтверждён.'
    )
