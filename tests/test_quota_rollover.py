from datetime import datetime, timezone
from pathlib import Path


def test_cloud_quota_uses_new_utc_day_after_midnight(monkeypatch):
    import quota

    class BeforeMidnight(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 5, 23, 59, 59, tzinfo=timezone.utc)

    class AfterMidnight(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 6, 0, 0, 1, tzinfo=timezone.utc)

    calls = []
    monkeypatch.setattr(quota, 'cloud_enabled', lambda: True)

    def fake_query(sql, params=None):
        calls.append((sql, list(params or [])))
        if 'SELECT requests FROM ai_usage' in sql:
            return {'results': []}
        return {'results': [{'requests': 1}]}

    monkeypatch.setattr(quota, '_cloud_query', fake_query)

    monkeypatch.setattr(quota, 'datetime', BeforeMidnight)
    assert quota.status()['used'] == 0
    assert calls[-1][1] == ['2026-09-05']
    assert quota.reserve() is True
    assert calls[-1][1][0] == '2026-09-05'

    monkeypatch.setattr(quota, 'datetime', AfterMidnight)
    assert quota.status()['used'] == 0
    assert calls[-1][1] == ['2026-09-06']
    assert quota.reserve() is True
    assert calls[-1][1][0] == '2026-09-06'


def test_d1_schema_has_openrouter_hard_cap_triggers():
    schema = (Path(__file__).resolve().parents[1] / 'cloud' / 'schema.sql').read_text(encoding='utf-8')
    assert 'CREATE TRIGGER IF NOT EXISTS ai_usage_cap_insert' in schema
    assert 'CREATE TRIGGER IF NOT EXISTS ai_usage_cap_update' in schema
    assert 'WHEN NEW.requests > 50' in schema
