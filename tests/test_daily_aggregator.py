import json
import zipfile
from pathlib import Path


def _write_article_zip(dest: Path, article_id: int, image_count: int):
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / f'article_{article_id}_test.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('package_manifest.json', json.dumps({'article_id': article_id, 'image_count': image_count}))
        zf.writestr('headline.txt', f'Article {article_id}')
        zf.writestr('article.md', '# test')
    return zip_path


def test_daily_aggregator_sends_once_for_three_ready_packages(monkeypatch, tmp_path):
    import aggregate_daily_package as agg

    monkeypatch.chdir(tmp_path)
    day = '2026-09-06'
    rows = [
        {'article_id': 101, 'batch_id': 1, 'source_run_id': 'r1', 'artifact_name': 'article-package-101-1'},
        {'article_id': 102, 'batch_id': 2, 'source_run_id': 'r2', 'artifact_name': 'article-package-102-2'},
        {'article_id': 103, 'batch_id': 3, 'source_run_id': 'r3', 'artifact_name': 'article-package-103-3'},
    ]
    counts = {101: 5, 102: 4, 103: 3}

    monkeypatch.setattr(agg, '_find_ready_day', lambda: day)

    def fake_query(sql, params=None):
        if 'SELECT article_id,batch_id,source_run_id,artifact_name' in sql:
            return {'results': rows}
        return {'results': []}

    monkeypatch.setattr(agg, 'query', fake_query)

    claims = iter([True, False])
    monkeypatch.setattr(agg, '_claim_day', lambda claimed_day, article_ids: next(claims))

    def fake_download(run_id, artifact_name, dest):
        article_id = int(artifact_name.split('-')[2])
        _write_article_zip(dest, article_id, counts[article_id])

    monkeypatch.setattr(agg, '_download_artifact', fake_download)

    sent = []
    monkeypatch.setattr(agg, 'send_document', lambda path, caption='': sent.append((Path(path), caption)) or 777)
    statuses = []
    monkeypatch.setattr(agg, '_set_day_status', lambda d, status, message_id=None: statuses.append((d, status, message_id)))

    agg.main()

    assert len(sent) == 1
    out, caption = sent[0]
    assert out.is_file()
    assert '5, 4, 3' in caption
    assert 'всего 12' in caption
    assert statuses[-1] == (day, 'sent', 777)

    with zipfile.ZipFile(out) as zf:
        manifest_name = next(name for name in zf.namelist() if name.endswith('/manifest.json'))
        manifest = json.loads(zf.read(manifest_name).decode('utf-8'))
    assert manifest['article_ids'] == [101, 102, 103]
    assert manifest['image_counts'] == [5, 4, 3]
    assert manifest['total_images'] == 12

    # Same day is already claimed: no duplicate Telegram send.
    agg.main()
    assert len(sent) == 1
