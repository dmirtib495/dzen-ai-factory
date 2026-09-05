from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from cloud_sync import query
from document_packager import MAX_APPROVED_IMAGES, MIN_APPROVED_IMAGES, build_article_package


def _find_batch_folder(root: Path, batch_id: int) -> Path:
    matches = [p for p in root.rglob(f'batch_{batch_id}') if p.is_dir()]
    if not matches:
        raise FileNotFoundError(f'batch_{batch_id} not found under {root}')
    return matches[0]


def _article_day(created_at: str) -> str:
    raw = (created_at or '').strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(ZoneInfo('Europe/Moscow')).date().isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Moscow')).date().isoformat()


def _subject_label(headline: str) -> str:
    text = (headline or '').strip()
    text = re.split(r'[:?—|]', text, maxsplit=1)[0].strip()
    text = re.sub(r'^(стоит ли брать|что купить|тест|обзор)\s+', '', text, flags=re.I).strip()
    return text[:90] or 'Автомобиль из материала'


def _captions(headline: str, image_count: int) -> list[str]:
    subject = _subject_label(headline)
    templates = [
        f'{subject}: внешний вид спереди в три четверти.',
        f'{subject}: вид сзади в три четверти.',
        f'{subject}: профиль кузова и основные пропорции.',
        f'{subject}: интерьер, передняя панель и рабочее место водителя.',
        f'{subject}: автомобиль в обычной дорожной обстановке.',
    ]
    return templates[:image_count]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--article-id', type=int, required=True)
    parser.add_argument('--batch-id', type=int, required=True)
    parser.add_argument('--source-root', default='source-artifact')
    args = parser.parse_args()

    batch_result = query(
        'SELECT id,article_id,status,candidate_json FROM image_batches WHERE id=?',
        [args.batch_id],
    ) or {}
    batches = batch_result.get('results', [])
    if not batches:
        raise SystemExit(f'Image batch #{args.batch_id} not found')
    batch = batches[0]
    if int(batch.get('article_id')) != args.article_id:
        raise SystemExit('Image batch/article mismatch')
    if batch.get('status') != 'approved':
        raise SystemExit(f"Image batch is not approved: {batch.get('status')}")

    article_result = query(
        'SELECT id,headline,article_markdown,created_at FROM articles WHERE id=? AND quality_ok=1',
        [args.article_id],
    ) or {}
    articles = article_result.get('results', [])
    if not articles:
        raise SystemExit(f'Quality-approved article #{args.article_id} not found')
    article = articles[0]
    headline = str(article.get('headline') or '')

    batch_folder = _find_batch_folder(Path(args.source_root), args.batch_id)
    candidates = json.loads(batch.get('candidate_json') or '[]')
    if len(candidates) < MIN_APPROVED_IMAGES or len(candidates) > MAX_APPROVED_IMAGES:
        raise SystemExit(
            f'Approved batch must contain {MIN_APPROVED_IMAGES}-{MAX_APPROVED_IMAGES} candidates; got {len(candidates)}'
        )
    images = [batch_folder / str(item['file']) for item in candidates]
    if any(not p.is_file() for p in images):
        raise SystemExit('One or more approved image files are missing from source artifact')

    image_count = len(images)
    captions = _captions(headline, image_count)
    folder, docx_path, zip_path = build_article_package(
        article_id=args.article_id,
        headline=headline,
        article_markdown=str(article.get('article_markdown') or ''),
        approved_images=images,
        output_root='data/packages',
        captions=captions,
    )

    now = datetime.now(timezone.utc)
    package_day = _article_day(str(article.get('created_at') or ''))
    run_id = os.getenv('GITHUB_RUN_ID', '').strip()
    artifact_name = f'article-package-{args.article_id}-{args.batch_id}'
    query(
        """
        INSERT INTO article_packages(
            article_id,batch_id,package_day,source_run_id,artifact_name,status,created_at,updated_at
        ) VALUES(?,?,?,?,?,'ready',?,?)
        ON CONFLICT(article_id) DO UPDATE SET
            batch_id=excluded.batch_id,
            package_day=excluded.package_day,
            source_run_id=excluded.source_run_id,
            artifact_name=excluded.artifact_name,
            status='ready',
            updated_at=excluded.updated_at
        """,
        [args.article_id, args.batch_id, package_day, run_id, artifact_name, now.isoformat(), now.isoformat()],
    )

    pointer = {
        'article_id': args.article_id,
        'batch_id': args.batch_id,
        'package_day': package_day,
        'image_count': image_count,
        'captions': captions,
        'folder': str(folder),
        'docx': str(docx_path),
        'zip': str(zip_path),
        'artifact_name': artifact_name,
    }
    Path('data/current_package.json').write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ARTICLE_PACKAGE_READY', json.dumps(pointer, ensure_ascii=False))


if __name__ == '__main__':
    main()
