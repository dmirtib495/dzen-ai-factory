import os
from datetime import datetime, timezone

# Cloudflare Free currently provides 10,000 neurons/day. The factory
# deliberately uses only 34 FLUX Schnell generations/day at the measured
# 172.8 neurons each, leaving >40% headroom for diagnostics/provider drift.
WORKERS_AI_FREE_DAILY_NEURON_LIMIT = 10_000.0
FLUX_SCHNELL_NEURONS_PER_IMAGE = 172.8
WORKERS_AI_DAILY_GENERATION_LIMIT = 34
WORKERS_AI_DAILY_NEURON_LIMIT = (
    FLUX_SCHNELL_NEURONS_PER_IMAGE * WORKERS_AI_DAILY_GENERATION_LIMIT
)
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
    """Atomically reserve Workers AI neurons before image inference.

    D1 is shared by scheduled article runs and image-regeneration runs. Failed
    inference remains conservatively reserved: this can under-use the allowance
    but prevents parallel runs from oversubscribing the free tier.
    """
    amount = float(amount)
    limit = float(limit)
    if amount <= 0:
        raise ValueError('Neuron reservation must be positive')
    if amount > limit:
        return False
    if not cloud_enabled():
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
            'generation_limit': WORKERS_AI_DAILY_GENERATION_LIMIT,
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
        'generation_limit': WORKERS_AI_DAILY_GENERATION_LIMIT,
        'free_tier_limit': WORKERS_AI_FREE_DAILY_NEURON_LIMIT,
    }
