from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from cloud_sync import query
from db import add_topic
import pipeline


def _decode_summary(raw: str) -> tuple[str, list[dict]]:
    text = str(raw or '').strip()
    if not text.startswith('{'):
        return text, []
    try:
        payload = json.loads(text)
    except Exception:
        return text, []
    if not isinstance(payload, dict):
        return text, []
    brief = str(payload.get('editorial_brief') or '').strip()
    sources = payload.get('sources') if isinstance(payload.get('sources'), list) else []
    clean_sources = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        clean_sources.append({
            'title': str(item.get('title') or ''),
            'url': str(item.get('url') or ''),
            'source': str(item.get('source') or ''),
            'summary': str(item.get('summary') or ''),
        })
    return brief or text, clean_sources


def _writer_summary(brief: str, sources: list[dict]) -> str:
    if not sources:
        return brief
    return (
        brief
        + '\n\nФАКТИЧЕСКАЯ БАЗА ДЛЯ МАТЕРИАЛА (несколько независимых исходников):\n'
        + json.dumps(sources, ensure_ascii=False, indent=2)
        + '\n\nИспользуй конкретные факты только из этой базы. Не придумывай отсутствующие характеристики, цены или неисправности.'
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--proposal-id', type=int, required=True)
    args = parser.parse_args()

    result = query(
        """
        SELECT p.id,p.group_id,p.title,p.link,p.source,p.summary,p.score,p.status,g.status AS group_status,g.selected_proposal_id
        FROM topic_proposals p
        JOIN topic_proposal_groups g ON g.id=p.group_id
        WHERE p.id=?
        """,
        [args.proposal_id],
    ) or {}
    rows = result.get('results', [])
    if not rows:
        raise SystemExit(f'Topic proposal #{args.proposal_id} not found')
    row = rows[0]
    if row.get('status') not in ('approved', 'generating'):
        raise SystemExit(f"Topic proposal #{args.proposal_id} is not approved: {row.get('status')}")
    if int(row.get('selected_proposal_id') or 0) != args.proposal_id:
        raise SystemExit('Proposal is not the selected option for its group')

    now = datetime.now(timezone.utc).isoformat()
    claimed = query(
        "UPDATE topic_proposals SET status='generating',updated_at=? WHERE id=? AND status='approved' RETURNING id",
        [now, args.proposal_id],
    ) or {}
    if not claimed.get('results') and row.get('status') != 'generating':
        raise SystemExit('Topic proposal could not be claimed')

    editorial_summary, source_bundle = _decode_summary(str(row.get('summary') or ''))
    summary_for_writer = _writer_summary(editorial_summary, source_bundle)
    primary_link = str(row.get('link') or '')
    primary_source = str(row.get('source') or '')
    if source_bundle:
        primary_link = str(source_bundle[0].get('url') or primary_link)
        primary_source = str(source_bundle[0].get('source') or primary_source)

    topic = {
        'id': add_topic(
            str(row.get('title') or ''),
            primary_link,
            primary_source,
            summary_for_writer,
            float(row.get('score') or 0),
        ),
        'title': str(row.get('title') or ''),
        'link': primary_link,
        'source': primary_source,
        'summary': summary_for_writer,
        'score': float(row.get('score') or 0),
        'source_bundle': source_bundle,
    }

    pipeline.collect_topics = lambda limit=40: [topic]
    pipeline.rank = lambda items: list(items)
    pipeline.recommended_categories = lambda: []

    try:
        made = pipeline.generate_batch()
    except Exception:
        query(
            "UPDATE topic_proposals SET status='approved',updated_at=? WHERE id=? AND status='generating'",
            [datetime.now(timezone.utc).isoformat(), args.proposal_id],
        )
        raise

    final_status = 'used' if made else 'approved'
    query(
        "UPDATE topic_proposals SET status=?,updated_at=? WHERE id=?",
        [final_status, datetime.now(timezone.utc).isoformat(), args.proposal_id],
    )
    print(f'APPROVED_TOPIC_RESULT proposal_id={args.proposal_id} made={made} status={final_status}')


if __name__ == '__main__':
    main()
