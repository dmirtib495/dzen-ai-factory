import os
from datetime import datetime, timezone

from db import reserve_ai_request, usage_today
from config import OPENROUTER_DAILY_LIMIT

CLOUD_KEYS = ('CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_D1_DATABASE_ID')


def cloud_enabled():
    return all(os.getenv(k, '').strip() for k in CLOUD_KEYS)


def _cloud_query(sql, params=None):
    from cloud_sync import query
    return query(sql, params or [])


def force_run_enabled():
    return os.getenv('FORCE_RUN', '').strip().lower() == 'true'


def reserve():
    """Atomically reserve one OpenRouter request from the shared daily budget.

    The reservation happens BEFORE the HTTP request. This intentionally counts
    every provider attempt, including requests that later return 429/5xx, because
    OpenRouter's free-tier request quota counts failed attempts too.

    When Cloudflare credentials are present, D1 is the shared source of truth for
    every scheduled GitHub Actions run. Without cloud credentials, the existing
    local SQLite atomic counter is used.
    """
    # An explicitly forced manual run bypasses only our internal D1/local
    # accounting guard. The provider still enforces its own external limits.
    # Do not increment ai_usage beyond 50: D1 intentionally has cap triggers.
    if force_run_enabled():
        return True

    if not cloud_enabled():
        return reserve_ai_request(OPENROUTER_DAILY_LIMIT)

    now = datetime.now(timezone.utc)
    day = now.date().isoformat()

    result = _cloud_query(
        """
        INSERT INTO ai_usage(day,requests,updated_at)
        VALUES(?,1,?)
        ON CONFLICT(day) DO UPDATE SET
            requests=ai_usage.requests+1,
            updated_at=excluded.updated_at
        WHERE ai_usage.requests < ?
        RETURNING requests
        """,
        [day, now.isoformat(), OPENROUTER_DAILY_LIMIT],
    ) or {}
    return bool(result.get('results', []))


def record_success():
    """Legacy compatibility helper; production accounting uses reserve()."""
    if not cloud_enabled():
        reserve_ai_request(1_000_000_000)
    return True


def status():
    if not cloud_enabled():
        used = usage_today()
        return {
            'used': used,
            'limit': OPENROUTER_DAILY_LIMIT,
            'remaining': max(0, OPENROUTER_DAILY_LIMIT - used),
            'mode': 'enforced_local',
        }

    day = datetime.now(timezone.utc).date().isoformat()
    result = _cloud_query("SELECT requests FROM ai_usage WHERE day=?", [day]) or {}
    rows = result.get('results', [])
    used = int(rows[0].get('requests', 0)) if rows else 0
    return {
        'used': used,
        'limit': OPENROUTER_DAILY_LIMIT,
        'remaining': max(0, OPENROUTER_DAILY_LIMIT - used),
        'mode': 'enforced_shared_d1',
    }
