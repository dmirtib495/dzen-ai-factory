import os
from db import reserve_ai_request, usage_today
from config import OPENROUTER_DAILY_LIMIT

CLOUD_KEYS=('CLOUDFLARE_API_TOKEN','CLOUDFLARE_ACCOUNT_ID','CLOUDFLARE_D1_DATABASE_ID')

def cloud_enabled(): return all(os.getenv(k,'').strip() for k in CLOUD_KEYS)

def _cloud_query(sql, params=None):
    from cloud_sync import query
    return query(sql, params or [])

def reserve():
    if not cloud_enabled():
        return reserve_ai_request(OPENROUTER_DAILY_LIMIT)
    from datetime import datetime, timezone
    day=datetime.now(timezone.utc).date().isoformat()
    _cloud_query("INSERT INTO ai_usage(day,requests,updated_at) VALUES(?,0,?) ON CONFLICT(day) DO NOTHING", [day, datetime.now(timezone.utc).isoformat()])
    result=_cloud_query("UPDATE ai_usage SET requests=requests+1,updated_at=? WHERE day=? AND requests<?", [datetime.now(timezone.utc).isoformat(),day,OPENROUTER_DAILY_LIMIT])
    return bool((result or {}).get('meta',{}).get('changes',0)==1)

def status():
    if not cloud_enabled():
        used=usage_today(); return {'used':used,'limit':OPENROUTER_DAILY_LIMIT,'remaining':max(0,OPENROUTER_DAILY_LIMIT-used)}
    from datetime import datetime, timezone
    day=datetime.now(timezone.utc).date().isoformat()
    result=_cloud_query("SELECT requests FROM ai_usage WHERE day=?", [day])
    rows=(result or {}).get('results',[])
    used=int(rows[0].get('requests',0)) if rows else 0
    return {'used':used,'limit':OPENROUTER_DAILY_LIMIT,'remaining':max(0,OPENROUTER_DAILY_LIMIT-used)}
