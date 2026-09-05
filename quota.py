import os
from db import reserve_ai_request, usage_today
from config import OPENROUTER_DAILY_LIMIT

CLOUD_KEYS = ('CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_D1_DATABASE_ID')


def cloud_enabled():
    return all(os.getenv(k, '').strip() for k in CLOUD_KEYS)


def _cloud_query(sql, params=None):
    from cloud_sync import query
    return query(sql, params or [])


def record_success():
    """Record a successful OpenRouter request without locally blocking the provider.

    OpenRouter is the source of truth for its actual free-tier/rate quota. The local
    counter is telemetry only; it must never prevent a request before the provider
    has had a chance to answer. This avoids false lockouts after retries/tests.
    """
    if not cloud_enabled():
        # A very high ceiling turns the existing atomic DB helper into a safe counter.
        reserve_ai_request(1_000_000_000)
        return True

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    _cloud_query(
        "INSERT INTO ai_usage(day,requests,updated_at) VALUES(?,0,?) ON CONFLICT(day) DO NOTHING",
        [day, now.isoformat()],
    )
    _cloud_query(
        "UPDATE ai_usage SET requests=requests+1,updated_at=? WHERE day=?",
        [now.isoformat(), day],
    )
    return True


def reserve():
    """Backward-compatible alias. Quota tracking no longer blocks requests."""
    return True


def status():
    if not cloud_enabled():
        used = usage_today()
        return {
            'used': used,
            'limit': OPENROUTER_DAILY_LIMIT,
            'remaining': max(0, OPENROUTER_DAILY_LIMIT - used),
            'mode': 'telemetry_only',
        }

    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).date().isoformat()
    result = _cloud_query("SELECT requests FROM ai_usage WHERE day=?", [day])
    rows = (result or {}).get('results', [])
    used = int(rows[0].get('requests', 0)) if rows else 0
    return {
        'used': used,
        'limit': OPENROUTER_DAILY_LIMIT,
        'remaining': max(0, OPENROUTER_DAILY_LIMIT - used),
        'mode': 'telemetry_only',
    }
