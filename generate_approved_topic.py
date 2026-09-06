from __future__ import annotations

import argparse
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from cloud_sync import query
from db import add_topic
import pipeline


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

    topic = {
        'id': add_topic(
            str(row.get('title') or ''),
            str(row.get('link') or ''),
            str(row.get('source') or ''),
            str(row.get('summary') or ''),
            float(row.get('score') or 0),
        ),
        'title': str(row.get('title') or ''),
        'link': str(row.get('link') or ''),
        'source': str(row.get('source') or ''),
        'summary': str(row.get('summary') or ''),
        'score': float(row.get('score') or 0),
    }

    # Use the proven production pipeline, but force it to see only the option
    # explicitly selected by the user in Telegram.
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
