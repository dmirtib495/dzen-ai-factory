from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from cloud_sync import query
from document_packager import build_article_package


def _find_batch_folder(root: Path, batch_id: int) -> Path:
    matches = [p for p in root.rglob(f'batch_{batch_id}') if p.is_dir()]
    if not matches:
        raise FileNotFoundError(f'batch_{batch_id} not found under {root}')
    return matches[0]


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
        'SELECT id,headline,article_markdown FROM articles WHERE id=? AND quality_ok=1',
        [args.article_id],
    ) or {}
    articles = article_result.get('results', [])
    if not articles:
        raise SystemExit(f'Quality-approved article #{args.article_id} not found')
    article = articles[0]

    batch_folder = _find_batch_folder(Path(args.source_root), args.batch_id)
    candidates = json.loads(batch.get('candidate_json') or '[]')
    if len(candidates) != 5:
        raise SystemExit(f'Approved batch must contain exactly 5 candidates; got {len(candidates)}')
    images = [batch_folder / str(item['file']) for item in candidates]
    if any(not p.is_file() for p in images):
        raise SystemExit('One or more approved image files are missing from source artifact')

    folder, docx_path, zip_path = build_article_package(
        article_id=args.article_id,
        headline=str(article.get('headline') or ''),
        article_markdown=str(article.get('article_markdown') or ''),
        approved_images=images,
        output_root='data/packages',
        captions=[f'Редакционная иллюстрация {i}' for i in range(1, 6)],
    )

    now = datetime.now(timezone.utc)
    package_day = now.astimezone(ZoneInfo('Europe/Moscow')).date().isoformat()
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
        'folder': str(folder),
        'docx': str(docx_path),
        'zip': str(zip_path),
        'artifact_name': artifact_name,
    }
    Path('data/current_package.json').write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ARTICLE_PACKAGE_READY', json.dumps(pointer, ensure_ascii=False))


if __name__ == '__main__':
    main()
