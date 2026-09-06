def test_image_quota_reserves_atomically_in_d1(monkeypatch):
    import image_quota

    captured = {}
    monkeypatch.setattr(image_quota, 'cloud_enabled', lambda: True)

    def fake_query(sql, params=None):
        captured['sql'] = sql
        captured['params'] = params
        return {'results': [{'used': 172.8}]}

    monkeypatch.setattr(image_quota, '_cloud_query', fake_query)
    assert image_quota.reserve_neurons(172.8) is True
    assert 'ON CONFLICT(day,resource) DO UPDATE' in captured['sql']
    assert 'resource_usage.used + excluded.used <= ?' in captured['sql']
    assert captured['params'][1] == image_quota.WORKERS_AI_RESOURCE
    assert captured['params'][2] == 172.8
    assert captured['params'][-1] == image_quota.WORKERS_AI_DAILY_NEURON_LIMIT
    assert image_quota.WORKERS_AI_DAILY_GENERATION_LIMIT == 50
    assert round(image_quota.WORKERS_AI_DAILY_NEURON_LIMIT, 1) == 5875.2
    assert image_quota.WORKERS_AI_DAILY_NEURON_LIMIT < image_quota.WORKERS_AI_FREE_DAILY_NEURON_LIMIT


def test_image_quota_refuses_when_shared_budget_is_exhausted(monkeypatch):
    import image_quota

    monkeypatch.setattr(image_quota, 'cloud_enabled', lambda: True)
    monkeypatch.setattr(image_quota, '_cloud_query', lambda sql, params=None: {'results': []})
    assert image_quota.reserve_neurons(172.8) is False


def test_image_quota_requires_cloud_for_production_safety(monkeypatch):
    import image_quota

    monkeypatch.setattr(image_quota, 'cloud_enabled', lambda: False)
    assert image_quota.reserve_neurons(172.8) is False
