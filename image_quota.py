import os
from datetime import datetime, timezone

WORKERS_AI_DAILY_NEURON_LIMIT = 10_000.0
WORKERS_AI_RESOURCE = 'workers_ai_neurons'

CLOUD_KEYS = (
    'CLOUDFLARE_API_TOKEN',
    'CLOUDFLARE_ACCOUNT_ID',
    'CLOUDFLARE_D1_DATABASE_ID',
)


def cloud_enabled():
    return all(os.getenv(k, '').strip() for k in CLOUD_KEYS)


def _cloud_query(sql, params=None):
    from cloud_sync import query
    return query(sql, params or [])


def reserve_neurons(amount: float, limit: float = WORKERS_AI_DAILY_NEURON_LIMIT) -> bool:
    """Atomically reserve Workers AI neurons before an image inference.

    D1 is the shared source of truth across all scheduled GitHub Actions runs.
    Reservation happens before calling Workers AI, which prevents concurrent
    runs from each assuming that the full daily free allocation is available.
    A failed inference remains conservatively reserved; this can under-use the
    free allocation but cannot oversubscribe it.
    """
    amount = float(amount)
    limit = float(limit)
    if amount <= 0:
        raise ValueError('Neuron reservation must be positive')
    if amount > limit:
        return False
    if not cloud_enabled():
        # Production image generation requires shared cloud quota protection.
        # Refuse rather than silently fall back to a process-local counter.
        return False

    now = datetime.now(timezone.utc)
    day = now.date().isoformat()
    result = _cloud_query(
        """
        INSERT INTO resource_usage(day,resource,used,updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(day,resource) DO UPDATE SET
            used=resource_usage.used+excluded.used,
            updated_at=excluded.updated_at
        WHERE resource_usage.used + excluded.used <= ?
        RETURNING used
        """,
        [day, WORKERS_AI_RESOURCE, amount, now.isoformat(), limit],
    ) or {}
    return bool(result.get('results', []))


def status(limit: float = WORKERS_AI_DAILY_NEURON_LIMIT) -> dict:
    limit = float(limit)
    if not cloud_enabled():
        return {
            'used': 0.0,
            'limit': limit,
            'remaining': limit,
            'resource': WORKERS_AI_RESOURCE,
            'mode': 'cloud_required',
        }

    day = datetime.now(timezone.utc).date().isoformat()
    result = _cloud_query(
        'SELECT used FROM resource_usage WHERE day=? AND resource=?',
        [day, WORKERS_AI_RESOURCE],
    ) or {}
    rows = result.get('results', [])
    used = float(rows[0].get('used', 0.0)) if rows else 0.0
    return {
        'used': used,
        'limit': limit,
        'remaining': max(0.0, limit - used),
        'resource': WORKERS_AI_RESOURCE,
        'mode': 'enforced_shared_d1',
    }
