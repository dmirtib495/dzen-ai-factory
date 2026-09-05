from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cloud_sync import query
from image_generator import editorial_prompts, generate_cloudflare_image, make_contact_sheet
from image_quota import FLUX_SCHNELL_NEURONS_PER_IMAGE, reserve_neurons, status as image_quota_status
from telegram_notify import notify_image_set

TARGET_IMAGES_PER_SET = 5
MIN_IMAGES_PER_SET = 3
BATCH_ROOT = Path('data/image_batches')


def _next_attempt(article_id: int) -> int:
    result = query(
        'SELECT COALESCE(MAX(attempt),0) n FROM image_batches WHERE article_id=?',
        [article_id],
    ) or {}
    rows = result.get('results', [])
    return int(rows[0].get('n', 0) if rows else 0) + 1


def _insert_batch(article_id: int, attempt: int, run_id: str, artifact_name: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    result = query(
        """
        INSERT INTO image_batches(
            article_id,attempt,status,source_run_id,artifact_name,
            candidate_json,created_at,updated_at
        ) VALUES(?,?, 'generating', ?, ?, '[]', ?, ?)
        RETURNING id
        """,
        [article_id, attempt, run_id, artifact_name, now, now],
    ) or {}
    rows = result.get('results', [])
    if not rows:
        raise RuntimeError('Could not create image batch in D1')
    return int(rows[0]['id'])


def _update_batch(batch_id: int, *, status: str, candidate_json: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if candidate_json is None:
        query('UPDATE image_batches SET status=?,updated_at=? WHERE id=?', [status, now, batch_id])
    else:
        query(
            'UPDATE image_batches SET status=?,candidate_json=?,updated_at=? WHERE id=?',
            [status, candidate_json, now, batch_id],
        )


def _reserve_adaptive_set() -> int:
    """Reserve the largest affordable set between 3 and 5 images.

    The first status read is advisory only. The actual reservation remains
    atomic in D1; if another workflow wins the race, retry with a smaller set.
    """
    quota = image_quota_status()
    remaining = float(quota.get('remaining', 0.0) or 0.0)
    affordable = int(remaining // FLUX_SCHNELL_NEURONS_PER_IMAGE)
    start = min(TARGET_IMAGES_PER_SET, affordable)
    for count in range(start, MIN_IMAGES_PER_SET - 1, -1):
        if reserve_neurons(FLUX_SCHNELL_NEURONS_PER_IMAGE * count):
            return count
    raise RuntimeError(
        f'Недостаточно общего дневного Workers AI бюджета даже для минимального набора '
        f'из {MIN_IMAGES_PER_SET} изображений'
    )


def generate_image_set(article_id: int, headline: str, *, artifact_prefix: str = 'dzen-factory') -> dict:
    """Generate a quota-aware 3-5 image set, persist it, and send one preview."""
    run_id = os.getenv('GITHUB_RUN_ID', '').strip() or 'local'
    run_number = os.getenv('GITHUB_RUN_NUMBER', '').strip() or run_id
    artifact_name = f'{artifact_prefix}-{run_number}'
    attempt = _next_attempt(article_id)
    batch_id = _insert_batch(article_id, attempt, run_id, artifact_name)

    try:
        image_count = _reserve_adaptive_set()
    except Exception:
        _update_batch(batch_id, status='quota_blocked')
        raise

    folder = BATCH_ROOT / f'batch_{batch_id}'
    folder.mkdir(parents=True, exist_ok=True)
    prompts = editorial_prompts(headline, image_count)
    candidates = []

    try:
        for idx, prompt in enumerate(prompts, 1):
            path = folder / f'image_{idx:02d}.jpg'
            meta = generate_cloudflare_image(prompt, path, quota_reserved=True)
            candidates.append({
                'index': idx,
                'file': path.name,
                'prompt': prompt,
                'neurons': meta['neurons'],
                'resolution': meta['resolution'],
            })

        contact = make_contact_sheet(
            [folder / x['file'] for x in candidates],
            folder / 'preview.jpg',
            headline,
        )
        manifest = {
            'batch_id': batch_id,
            'article_id': article_id,
            'attempt': attempt,
            'headline': headline,
            'source_run_id': run_id,
            'artifact_name': artifact_name,
            'image_count': image_count,
            'images': candidates,
            'preview': contact.name,
        }
        (folder / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        _update_batch(batch_id, status='pending_review', candidate_json=json.dumps(candidates, ensure_ascii=False))

        message_id = notify_image_set(
            contact,
            headline=headline,
            batch_id=batch_id,
            attempt=attempt,
            image_count=image_count,
        )
        if not message_id:
            raise RuntimeError('Telegram не подтвердил доставку превью набора изображений')
        query(
            'UPDATE image_batches SET telegram_message_id=?,updated_at=? WHERE id=?',
            [int(message_id), datetime.now(timezone.utc).isoformat(), batch_id],
        )
        return manifest
    except Exception:
        _update_batch(batch_id, status='generation_failed', candidate_json=json.dumps(candidates, ensure_ascii=False))
        raise


def generate_existing_article_set(article_id: int, *, artifact_prefix: str = 'image-batch') -> dict:
    result = query('SELECT headline FROM articles WHERE id=?', [article_id]) or {}
    rows = result.get('results', [])
    if not rows:
        raise RuntimeError(f'Article #{article_id} not found in D1')
    return generate_image_set(article_id, str(rows[0].get('headline') or ''), artifact_prefix=artifact_prefix)
