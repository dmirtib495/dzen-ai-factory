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


def _candidates():
    names = [
        'Toyota RAV4, 2019 г.', 'Hyundai Palisade, 2022 г.', 'Mazda CX-30, 2021 г.',
        'Nissan X-Trail, 2018 г.', 'Skoda Kodiaq, 2020 г.', 'Honda CR-V, 2019 г.',
        'Kia Sportage, 2021 г.', 'Volkswagen Tiguan, 2020 г.', 'Subaru Forester, 2019 г.',
        'Mitsubishi Outlander, 2020 г.', 'Geely Monjaro, 2023 г.', 'Haval Dargo, 2023 г.',
    ]
    return [_item(title, idx=i) for i, title in enumerate(names, 1)]


def test_choice_set_has_mandatory_editorial_diversity():
    choices = build_diverse_choices(_candidates(), history=[])
    assert len(choices) == 5
    assert [x['format'] for x in choices] == ['single', 'single', 'comparison', 'practical', 'market']
    assert 'Что выбрать:' in choices[2]['title']
    assert 'с пробегом:' in choices[3]['title']
    assert 'Пять интересных автомобилей' in choices[4]['title']


def test_derived_topics_preserve_multiple_source_evidence():
    comparison = build_diverse_choices(_candidates(), history=[])[2]
    brief, sources = _decode_summary(comparison['summary'])
    assert 'сравнение' in brief.lower()
    assert len(sources) == 3
    writer = _writer_summary(brief, sources)
    assert 'ФАКТИЧЕСКАЯ БАЗА' in writer
    assert 'https://example.com/3' in writer
    assert 'https://example.com/5' in writer
