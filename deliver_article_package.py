from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cloud_sync import query
from telegram_notify import send_document


def _claim(article_id: int, batch_id: int) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    result = query(
        """
        INSERT INTO article_package_deliveries(
            article_id,batch_id,status,telegram_message_id,created_at,updated_at
        ) VALUES(?,?,'sending',NULL,?,?)
        ON CONFLICT(article_id,batch_id) DO NOTHING
        RETURNING article_id
        """,
        [article_id, batch_id, now, now],
    ) or {}
    return bool(result.get('results', []))


def _release_failed_claim(article_id: int, batch_id: int) -> None:
    query(
        "DELETE FROM article_package_deliveries WHERE article_id=? AND batch_id=? AND status='sending'",
        [article_id, batch_id],
    )


def deliver(pointer_path: str | Path = 'data/current_package.json') -> int | None:
    pointer = json.loads(Path(pointer_path).read_text(encoding='utf-8'))
    article_id = int(pointer['article_id'])
    batch_id = int(pointer['batch_id'])
    zip_path = Path(pointer['zip'])
    image_count = int(pointer['image_count'])

    if not zip_path.is_file() or zip_path.stat().st_size <= 0:
        raise FileNotFoundError(str(zip_path))

    if not _claim(article_id, batch_id):
        existing = query(
            "SELECT status,telegram_message_id FROM article_package_deliveries WHERE article_id=? AND batch_id=?",
            [article_id, batch_id],
        ) or {}
        rows = existing.get('results', [])
        status = rows[0].get('status') if rows else 'unknown'
        message_id = rows[0].get('telegram_message_id') if rows else None
        print(
            f'ARTICLE_PACKAGE_DELIVERY_SKIPPED article_id={article_id} batch_id={batch_id} '
            f'status={status} message_id={message_id}'
        )
        return int(message_id) if message_id is not None else None

    try:
        article = query('SELECT headline FROM articles WHERE id=?', [article_id]) or {}
        rows = article.get('results', [])
        headline = str(rows[0].get('headline') or '') if rows else ''
        message_id = send_document(
            zip_path,
            caption=(
                f'📦 Готовая статья #{article_id}\n'
                f'{headline}\n\n'
                f'В ZIP: Word с {image_count} изображениями по тексту + '
                f'{image_count} оригинальных JPG + исходный Markdown.'
            ),
        )
        if not message_id:
            raise RuntimeError('Telegram did not return message_id for article ZIP')

        now = datetime.now(timezone.utc).isoformat()
        query(
            """
            UPDATE article_package_deliveries
            SET status='sent',telegram_message_id=?,updated_at=?
            WHERE article_id=? AND batch_id=? AND status='sending'
            """,
            [int(message_id), now, article_id, batch_id],
        )
        print(
            f'ARTICLE_PACKAGE_DELIVERED article_id={article_id} batch_id={batch_id} '
            f'message_id={message_id}'
        )
        return int(message_id)
    except Exception:
        # Ordinary API failures remain retryable. A hard runner crash after a
        # successful Telegram response intentionally leaves status='sending',
        # which favors duplicate prevention over an automatic duplicate resend.
        _release_failed_claim(article_id, batch_id)
        raise


def main() -> None:
    deliver()


if __name__ == '__main__':
    main()
