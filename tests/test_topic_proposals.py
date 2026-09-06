from propose_topics import build_diverse_choices
from generate_approved_topic import _decode_summary, _writer_summary


def _item(title, score=50, idx=0):
    return {
        'title': title,
        'link': f'https://example.com/{idx}',
        'source': 'test-rss',
        'summary': f'Фактическая выжимка для {title}',
        'score': score - idx,
        'trend_title': '',
        'trend_views': 0,
        'trend_channel': '',
    }


def test_choice_set_has_mandatory_editorial_diversity():
    candidates = [
        _item('Toyota RAV4, 2019 г.', idx=1),
        _item('Hyundai Palisade, 2022 г.', idx=2),
        _item('Mazda CX-30, 2021 г.', idx=3),
        _item('Nissan X-Trail, 2018 г.', idx=4),
        _item('Skoda Kodiaq, 2020 г.', idx=5),
        _item('Honda CR-V, 2019 г.', idx=6),
        _item('Kia Sportage, 2021 г.', idx=7),
        _item('Volkswagen Tiguan, 2020 г.', idx=8),
        _item('Subaru Forester, 2019 г.', idx=9),
        _item('Mitsubishi Outlander, 2020 г.', idx=10),
        _item('Geely Monjaro, 2023 г.', idx=11),
        _item('Haval Dargo, 2023 г.', idx=12),
    ]
    choices = build_diverse_choices(candidates, history=[])
    assert len(choices) == 5
    assert [x['format'] for x in choices] == ['single', 'single', 'comparison', 'practical', 'market']
    assert 'Что выбрать:' in choices[2]['title']
    assert 'с пробегом:' in choices[3]['title']
    assert 'Пять интересных автомобилей' in choices[4]['title']


def test_derived_topics_preserve_multiple_source_evidence():
    candidates = [_item(f'Model {i}, 2020 г.', idx=i) for i in range(1, 13)]
    comparison = build_diverse_choices(candidates, history=[])[2]
    brief, sources = _decode_summary(comparison['summary'])
    assert 'сравнение' in brief.lower()
    assert len(sources) == 3
    writer = _writer_summary(brief, sources)
    assert 'ФАКТИЧЕСКАЯ БАЗА' in writer
    assert 'https://example.com/3' in writer
    assert 'https://example.com/5' in writer
