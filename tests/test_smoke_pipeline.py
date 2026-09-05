import types

import pytest


def test_config_rejects_each_missing_yandex_value(monkeypatch):
    import config
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr(config, 'YANDEX_API_KEY', '')
    monkeypatch.setattr(config, 'YANDEX_FOLDER_ID', 'folder')
    errors = config.validate()
    assert any('YANDEX_API_KEY не задан' in x for x in errors)

    monkeypatch.setattr(config, 'YANDEX_API_KEY', 'key')
    monkeypatch.setattr(config, 'YANDEX_FOLDER_ID', '')
    errors = config.validate()
    assert any('YANDEX_FOLDER_ID не задан' in x for x in errors)


def test_ai_writer_rejects_missing_source_before_provider(monkeypatch):
    import ai_writer
    called = {'draft': False}

    def forbidden(_topic):
        called['draft'] = True
        raise AssertionError('provider must not be called')

    monkeypatch.setattr(ai_writer, '_draft', forbidden)
    with pytest.raises(ValueError, match='реального URL'):
        ai_writer.generate_article({'title': 'Автомобиль', 'link': ''})
    assert not called['draft']


def test_yandex_stage_fails_before_http_when_credentials_missing(monkeypatch):
    import ai_writer
    monkeypatch.setattr(ai_writer, 'YANDEX_API_KEY', '')
    monkeypatch.setattr(ai_writer, 'YANDEX_FOLDER_ID', '')
    monkeypatch.setattr(ai_writer.requests, 'post', lambda *a, **k: (_ for _ in ()).throw(AssertionError('HTTP must not be called')))
    with pytest.raises(RuntimeError, match='YANDEX_API_KEY'):
        ai_writer._yandex_edit({'headline': 'x', 'article_markdown': 'y'})


def test_topic_hunter_accepts_live_shaped_english_auto_item(monkeypatch):
    import topic_hunter
    entry = types.SimpleNamespace(
        title='Used Toyota SUV maintenance cost review',
        link='https://example.com/car',
        summary='What to check before you buy this vehicle',
        published_parsed=None,
    )
    feed = types.SimpleNamespace(entries=[entry], feed={'title': 'Test feed'}, bozo=0)
    monkeypatch.setattr(topic_hunter, 'RSS_SOURCES', ['https://example.com/feed.xml'])
    monkeypatch.setattr(topic_hunter.feedparser, 'parse', lambda _url: feed)
    monkeypatch.setattr(topic_hunter, 'topic_seen', lambda _title: False)
    monkeypatch.setattr(topic_hunter, 'add_topic', lambda *args: 123)
    topics = topic_hunter.collect_topics(5)
    assert len(topics) == 1
    assert topics[0]['id'] == 123
    assert topics[0]['link'].startswith('https://')


def test_pipeline_handles_empty_topic_feed_without_provider_call(monkeypatch):
    import pipeline

    class DummyLock:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    notices = []
    monkeypatch.setattr(pipeline, 'RunLock', DummyLock)
    monkeypatch.setattr(pipeline, 'hydrate_local', lambda: 0)
    monkeypatch.setattr(pipeline, 'backup_db', lambda: None)
    monkeypatch.setattr(pipeline, 'learn_strategy', lambda: {})
    monkeypatch.setattr(pipeline, 'recommended_categories', lambda: [])
    monkeypatch.setattr(pipeline, 'collect_topics', lambda _limit: [])
    monkeypatch.setattr(pipeline, 'rank', lambda items: items)
    monkeypatch.setattr(pipeline, 'sync_local', lambda: 0)
    monkeypatch.setattr(pipeline, 'generate_article', lambda _topic: (_ for _ in ()).throw(AssertionError('provider must not run')))
    monkeypatch.setattr(pipeline, 'notify', notices.append)
    assert pipeline.generate_batch() == 0
    assert notices


def test_quota_record_success_is_telemetry_only(monkeypatch):
    import quota
    calls = []
    monkeypatch.setattr(quota, 'cloud_enabled', lambda: False)
    monkeypatch.setattr(quota, 'reserve_ai_request', lambda limit: calls.append(limit) or True)
    assert quota.record_success() is True
    assert calls == [1_000_000_000]
