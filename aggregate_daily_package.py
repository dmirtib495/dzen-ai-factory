from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

from cloud_sync import query
from telegram_notify import send_document

REPO = 'dmirtib495/dzen-ai-factory'
ARTICLES_PER_DAILY_PACK = 3
TELEGRAM_SAFE_ZIP_BYTES = 49 * 1024 * 1024


def _claim_day(day: str, article_ids: list[int]) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    result = query(
        """
        INSERT INTO daily_packages(day,status,telegram_message_id,article_ids_json,created_at,updated_at)
        VALUES(?,'building',NULL,?,?,?)
        ON CONFLICT(day) DO UPDATE SET
            status='building',
            article_ids_json=excluded.article_ids_json,
            updated_at=excluded.updated_at
        WHERE daily_packages.status='failed'
        RETURNING day
        """,
        [day, json.dumps(article_ids), now, now],
    ) or {}
    return bool(result.get('results', []))


def _set_day_status(day: str, status: str, message_id: int | None = None) -> None:
    query(
        'UPDATE daily_packages SET status=?,telegram_message_id=?,updated_at=? WHERE day=?',
        [status, message_id, datetime.now(timezone.utc).isoformat(), day],
    )


def _download_artifact(run_id: str, artifact_name: str, dest: Path) -> None:
    token = os.getenv('GITHUB_TOKEN', '').strip()
    if not token:
        raise RuntimeError('GITHUB_TOKEN is required for cross-run artifact download')
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    listing = requests.get(
        f'https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts',
        headers=headers,
        timeout=30,
    )
    listing.raise_for_status()
    artifacts = listing.json().get('artifacts', [])
    match = next((a for a in artifacts if a.get('name') == artifact_name and not a.get('expired')), None)
    if not match:
        raise RuntimeError(f'Artifact {artifact_name!r} not found on run {run_id}')
    archive = requests.get(match['archive_download_url'], headers=headers, timeout=120)
    archive.raise_for_status()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        zf.extractall(dest)


def _find_inner_article_zip(root: Path, article_id: int) -> Path:
    candidates = [p for p in root.rglob(f'article_{article_id}_*.zip') if p.is_file()]
    if not candidates:
        raise FileNotFoundError(f'Inner article ZIP for #{article_id} not found under {root}')
    return candidates[0]


def main():
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo('Europe/Moscow')).date().isoformat()
    result = query(
        """
        SELECT article_id,batch_id,source_run_id,artifact_name
        FROM article_packages
        WHERE package_day=? AND status='ready'
        ORDER BY article_id
        LIMIT ?
        """,
        [day, ARTICLES_PER_DAILY_PACK],
    ) or {}
    rows = result.get('results', [])
    if len(rows) < ARTICLES_PER_DAILY_PACK:
        print(f'DAILY_PACKAGE_WAIT day={day} ready={len(rows)}/{ARTICLES_PER_DAILY_PACK}')
        return

    article_ids = [int(row['article_id']) for row in rows]
    if not _claim_day(day, article_ids):
        print(f'DAILY_PACKAGE_ALREADY_CLAIMED day={day}')
        return

    work = Path('data/daily_pack_work')
    shutil.rmtree(work, ignore_errors=True)
    master = work / f'Dzen_Daily_{day}'
    master.mkdir(parents=True, exist_ok=True)
    current_run = os.getenv('GITHUB_RUN_ID', '').strip()

    try:
        for pos, row in enumerate(rows, 1):
            article_id = int(row['article_id'])
            run_id = str(row.get('source_run_id') or '')
            artifact_name = str(row.get('artifact_name') or '')

            if run_id == current_run:
                source_root = Path('data/packages')
            else:
                source_root = work / f'artifact_{article_id}'
                _download_artifact(run_id, artifact_name, source_root)

            inner_zip = _find_inner_article_zip(source_root, article_id)
            article_dest = master / f'{pos:02d}_article_{article_id}'
            article_dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(inner_zip) as zf:
                zf.extractall(article_dest)

        manifest = {
            'day': day,
            'article_ids': article_ids,
            'articles': ARTICLES_PER_DAILY_PACK,
            'images_per_article': 5,
            'created_at': now.isoformat(),
        }
        (master / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

        out = Path('data/daily_packages') / f'Dzen_Daily_{day}.zip'
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(master.rglob('*')):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(master.parent)))

        size = out.stat().st_size
        print(f'DAILY_ZIP_SIZE bytes={size}')
        if size > TELEGRAM_SAFE_ZIP_BYTES:
            raise RuntimeError(
                f'Daily ZIP is {size / 1024 / 1024:.1f} MB, above the factory Telegram safety limit '
                f'{TELEGRAM_SAFE_ZIP_BYTES / 1024 / 1024:.0f} MB'
            )

        message_id = send_document(
            out,
            caption=(
                f'📦 Ежедневный пакет Dzen AI Factory за {day}\n'
                f'3 статьи · по 5 подтверждённых изображений · DOCX + отдельные JPG'
            ),
        )
        _set_day_status(day, 'sent', int(message_id))
        print(f'DAILY_PACKAGE_SENT day={day} message_id={message_id} path={out}')
    except Exception:
        _set_day_status(day, 'failed')
        raise


if __name__ == '__main__':
    main()
