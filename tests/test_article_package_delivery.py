import json
from pathlib import Path

from PIL import Image
from docx import Document


def _make_images(root: Path, count: int = 3) -> list[Path]:
    paths = []
    for idx in range(count):
        path = root / f'image_{idx + 1}.jpg'
        Image.new('RGB', (640, 480), (80 + idx * 20, 100, 120)).save(path, 'JPEG')
        paths.append(path)
    return paths


def test_docx_places_images_and_captions_inside_article_flow(tmp_path):
    from document_packager import build_article_docx

    images = _make_images(tmp_path, 3)
    article = '\n\n'.join([
        'Вступление о модели и причинах интереса к ней.',
        'Первый смысловой абзац о рынке и предложении.',
        '## Кузов и техника',
        'Подробности по кузову, платформе и силовой установке.',
        'Ещё один абзац о поведении автомобиля на дороге.',
        '## Салон и оснащение',
        'Описание салона, панели приборов и мультимедийной системы.',
        'Практические особенности повседневной эксплуатации.',
        '## Что проверить перед покупкой',
        'Финальный чек-лист и вывод для покупателя.',
    ])
    captions = ['Общий вид.', 'Профиль автомобиля.', 'Интерьер автомобиля.']
    output = tmp_path / 'article.docx'

    build_article_docx(
        headline='Тестовый автомобиль',
        article_markdown=article,
        approved_images=images,
        output_path=output,
        captions=captions,
    )

    doc = Document(output)
    texts = [p.text for p in doc.paragraphs]
    caption_positions = [i for i, text in enumerate(texts) if text.startswith('Рис. ')]

    assert len(doc.inline_shapes) == 3
    assert len(caption_positions) == 3
    assert 'Иллюстрации' not in texts
    assert caption_positions == sorted(caption_positions)
    # At least the first two figures must have article text after them; this
    # proves the document is not built as text + an image appendix.
    final_article_index = texts.index('Финальный чек-лист и вывод для покупателя.')
    assert caption_positions[0] < final_article_index
    assert caption_positions[1] < final_article_index
    assert any('Общий вид.' in text for text in texts)
    assert any('Интерьер автомобиля.' in text for text in texts)


def test_individual_zip_delivery_is_idempotent(monkeypatch, tmp_path):
    import deliver_article_package as delivery

    zip_path = tmp_path / 'article.zip'
    zip_path.write_bytes(b'PK-test-package')
    pointer = tmp_path / 'current_package.json'
    pointer.write_text(json.dumps({
        'article_id': 8,
        'batch_id': 1,
        'zip': str(zip_path),
        'image_count': 5,
    }), encoding='utf-8')

    state = {'delivery': None}

    def fake_query(sql, params=None):
        compact = ' '.join(sql.split())
        if compact.startswith('INSERT INTO article_package_deliveries'):
            if state['delivery'] is not None:
                return {'results': []}
            state['delivery'] = {'status': 'sending', 'telegram_message_id': None}
            return {'results': [{'article_id': 8}]}
        if 'SELECT status,telegram_message_id FROM article_package_deliveries' in compact:
            return {'results': [dict(state['delivery'])] if state['delivery'] else []}
        if compact.startswith('SELECT headline FROM articles'):
            return {'results': [{'headline': 'Toyota Crown 210 из Японии'}]}
        if compact.startswith('UPDATE article_package_deliveries'):
            state['delivery'] = {'status': 'sent', 'telegram_message_id': int(params[0])}
            return {'results': []}
        if compact.startswith('DELETE FROM article_package_deliveries'):
            state['delivery'] = None
            return {'results': []}
        raise AssertionError(compact)

    monkeypatch.setattr(delivery, 'query', fake_query)
    sent = []
    monkeypatch.setattr(
        delivery,
        'send_document',
        lambda path, caption='': sent.append((Path(path), caption)) or 555,
    )

    assert delivery.deliver(pointer) == 555
    assert delivery.deliver(pointer) == 555
    assert len(sent) == 1
    assert state['delivery'] == {'status': 'sent', 'telegram_message_id': 555}
    assert '5 оригинальных JPG' in sent[0][1]
