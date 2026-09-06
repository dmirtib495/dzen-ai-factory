import json
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


def test_openrouter_json_retries_malformed_response_and_records_actual_model(monkeypatch):
    import ai_writer
    replies = iter([
        types.SimpleNamespace(model='free/model-a', choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='not json'))]),
        types.SimpleNamespace(model='free/model-b', choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"headline":"ok"}'))]),
    ])
    calls = []
    def fake_call(model, messages, temperature=0.2):
        calls.append((model, messages[-1]['content']))
        return next(replies)
    monkeypatch.setattr(ai_writer, '_or_call', fake_call)
    parsed, requested, actual = ai_writer._openrouter_json(['openrouter/free'], 'prompt', 'test-role', 0.0, 'test')
    assert parsed == {'headline': 'ok'}
    assert requested == 'openrouter/free'
    assert actual == 'free/model-b'
    assert len(calls) == 2
    assert 'ПОВТОР ПОСЛЕ ОШИБКИ ФОРМАТА' in calls[1][1]


def _publication_grade_data():
    sections = []
    names = [
        'Что проверить до осмотра',
        'Кузов и следы ремонта',
        'Салон и электрика',
        'Проверка на ходу',
        'Практический чек-лист',
        'Где можно ошибиться или переплатить',
    ]
    for i, name in enumerate(names):
        words = ' '.join(f'проверка{i}_{j}' for j in range(155))
        prefix = 'Практический чек-лист и риск расходов. ' if i == 4 else ('Риск переплаты снижают последовательной проверкой. ' if i == 5 else 'Проверяйте состояние последовательно. ')
        sections.append(f'## {name}\n\n{prefix}{words}.')
    return {
        'headline': 'Как проверить подержанный автомобиль перед покупкой без лишней переплаты',
        'headlines': ['Как проверить подержанный автомобиль перед покупкой без лишней переплаты'],
        'category': 'Экономия',
        'article_markdown': '\n\n'.join(sections),
        'fact_check': [
            'Проверить: состояние кузова требует отдельного осмотра',
            'Проверить: работу электрики нужно оценивать до сделки',
            'Проверить: тест-драйв помогает выявить заметные отклонения',
        ],
        'image_prompt': 'Photorealistic editorial automotive inspection scene in natural daylight, no text or logos.',
        'source_urls': ['https://example.com/source'],
        'commercial_intent': 4,
        'ai_stages': ['FixedFree/OpenRouter:model', 'YandexGPT:yandexgpt/latest', 'OpenAI/OpenRouter:model'],
    }


def test_quality_audit_uses_yandex_only_for_openrouter_daily_free_limit(monkeypatch, caplog):
    import ai_writer

    data = _publication_grade_data()
    monkeypatch.setattr(ai_writer, 'YANDEX_API_KEY', 'test-yandex-key')
    monkeypatch.setattr(ai_writer, 'YANDEX_FOLDER_ID', 'test-folder')
    monkeypatch.setattr(ai_writer, 'YANDEX_MODEL', 'yandexgpt/latest')
    monkeypatch.setattr(
        ai_writer,
        '_openrouter_json',
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('Error code: 429 - Rate limit exceeded: free-models-per-day; limit_source=openrouter_free_tier_daily')
        ),
    )

    captured = {}
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                'result': {
                    'alternatives': [{
                        'message': {
                            'text': json.dumps({
                                'verdict': 'PASS',
                                'total_score': 96,
                                'scores': {'facts': 29, 'utility': 20, 'editorial': 18, 'structure': 15, 'ethics': 14},
                                'blocking_issues': [],
                                'improvements': [],
                                'fact_risks': [],
                                'strengths': ['Практическая структура'],
                            }, ensure_ascii=False)
                        }
                    }]
                }
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['url'] = url
        captured['body'] = json
        return FakeResponse()

    monkeypatch.setattr(ai_writer.requests, 'post', fake_post)
    audit = ai_writer._quality_audit(data)

    assert audit['verdict'] == 'PASS'
    assert audit['total_score'] == 96
    assert audit['blocking_issues'] == []
    assert audit['auditor_provider'] == 'QualityAudit/YandexFallback'
    assert audit['auditor_model'] == 'yandexgpt/latest'
    assert data['ai_quality_audit'] == audit
    assert any('QualityAudit/YandexFallback' in stage for stage in data['ai_stages'])
    prompt = captured['body']['messages'][1]['text']
    assert 'Ты НЕ участвовал в создании или редактуре этого текста' in prompt
    assert 'FixedFree/OpenRouter:model' not in prompt
    assert 'YandexGPT:yandexgpt/latest' not in prompt
    assert 'QUALITY_AUDIT_FALLBACK' in caplog.text


def test_generate_article_completes_with_yandex_audit_fallback(monkeypatch):
    import ai_writer

    topic = {
        'title': 'Проверка подержанного автомобиля',
        'source': 'Test RSS',
        'link': 'https://example.com/source',
        'summary': 'Практический материал о проверке автомобиля перед покупкой.',
    }
    base = _publication_grade_data()
    monkeypatch.setattr(ai_writer, 'YANDEX_API_KEY', 'test-yandex-key')
    monkeypatch.setattr(ai_writer, 'YANDEX_FOLDER_ID', 'test-folder')
    monkeypatch.setattr(ai_writer, 'YANDEX_MODEL', 'yandexgpt/latest')
    monkeypatch.setattr(ai_writer, '_draft', lambda _topic: dict(base))
    monkeypatch.setattr(ai_writer, '_yandex_edit', lambda data: dict(data))
    monkeypatch.setattr(ai_writer, '_final_edit', lambda data, repair_notes='': dict(data))
    monkeypatch.setattr(
        ai_writer,
        '_openrouter_json',
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('429 free-models-per-day openrouter_free_tier_daily')
        ),
    )

    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {'result': {'alternatives': [{'message': {'text': json.dumps({
                'verdict': 'PASS',
                'total_score': 95,
                'scores': {'facts': 28, 'utility': 20, 'editorial': 18, 'structure': 15, 'ethics': 14},
                'blocking_issues': [],
                'improvements': [],
                'fact_risks': [],
                'strengths': ['Готово к публикации'],
            }, ensure_ascii=False)}}]}}

    monkeypatch.setattr(ai_writer.requests, 'post', lambda *a, **k: FakeResponse())
    result = ai_writer.generate_article(topic)
    quality = ai_writer.check_article(result, require_ai_audit=True)

    assert quality['ok'] is True
    assert quality['score'] >= 90
    assert quality['problems'] == []
    assert result['ai_quality_audit']['verdict'] == 'PASS'
    assert result['ai_quality_audit']['auditor_provider'] == 'QualityAudit/YandexFallback'


def test_quality_audit_does_not_fallback_on_unrelated_429(monkeypatch):
    import ai_writer

    data = _publication_grade_data()
    monkeypatch.setattr(
        ai_writer,
        '_openrouter_json',
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Error code: 429 temporary provider rate limit')),
    )
    monkeypatch.setattr(
        ai_writer,
        '_yandex_quality_audit',
        lambda _data: (_ for _ in ()).throw(AssertionError('Yandex fallback must not run')),
    )
    with pytest.raises(RuntimeError, match='temporary provider rate limit'):
        ai_writer._quality_audit(data)


def test_rss_html_named_entities_become_xml_safe():
    import topic_hunter
    raw = '<description>&laquo;тест&raquo; &amp; ok</description>'
    safe = topic_hunter._xml_safe_named_entities(raw)
    assert '&laquo;' not in safe and '&raquo;' not in safe
    assert '&#171;' in safe and '&#187;' in safe
    assert '&amp;' in safe


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
    monkeypatch.setattr(topic_hunter, '_parse_feed', lambda _url: feed)
    monkeypatch.setattr(topic_hunter, 'topic_seen', lambda _title: False)
    monkeypatch.setattr(topic_hunter, 'add_topic', lambda *args: 123)
    topics = topic_hunter.collect_topics(5)
    assert len(topics) == 1
    assert topics[0]['id'] == 123
    assert topics[0]['link'].startswith('https://')


def test_topic_hunter_skips_malformed_entry_without_crashing(monkeypatch):
    import topic_hunter
    class BadValue:
        def __str__(self):
            raise RuntimeError('broken entry')
    bad = types.SimpleNamespace(title=BadValue(), link='https://example.com/bad', summary='', published_parsed=None)
    good = types.SimpleNamespace(title='Toyota car maintenance review', link='https://example.com/good', summary='buy cost repair', published_parsed=None)
    feed = types.SimpleNamespace(entries=[bad, good], feed={'title': 'Test feed'}, bozo=1, bozo_exception=ValueError('bad xml'))
    monkeypatch.setattr(topic_hunter, 'RSS_SOURCES', ['https://example.com/feed.xml'])
    monkeypatch.setattr(topic_hunter, '_parse_feed', lambda _url: feed)
    monkeypatch.setattr(topic_hunter, 'topic_seen', lambda _title: False)
    monkeypatch.setattr(topic_hunter, 'add_topic', lambda *args: 321)
    topics = topic_hunter.collect_topics(5)
    assert len(topics) == 1
    assert topics[0]['link'] == 'https://example.com/good'


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


def test_final_length_fit_removes_complete_sentences_without_truncation(monkeypatch):
    import ai_writer

    monkeypatch.setattr(ai_writer, 'MIN_ARTICLE_WORDS', 20)
    monkeypatch.setattr(ai_writer, 'MAX_ARTICLE_WORDS', 35)
    data = {
        'article_markdown': (
            '## Раздел\n\n'
            'Первое предложение содержит полезную проверку автомобиля перед покупкой. '
            'Второе предложение объясняет возможный риск дополнительных расходов после сделки. '
            'Третье предложение предлагает провести независимую диагностику перед оплатой. '
            'Четвертое предложение повторяет второстепенную рекомендацию для осторожного покупателя.'
        ),
        'ai_stages': [],
    }

    result = ai_writer._fit_article_to_limits(data)

    assert ai_writer._russian_word_count(result['article_markdown']) <= 35
    assert result['article_markdown'].rstrip().endswith(('.', '!', '?'))
    assert 'Deterministic:final-length-fit' in result['ai_stages']
