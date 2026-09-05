from title_lab import rank_titles
from quality_checker import check_article
from quota import status


def test_title_lab():
    x = rank_titles(['Купить авто: 7 ошибок перед сделкой', '100% лучший автомобиль!!!'], 'Что купить')
    assert x[0]['title'] == 'Купить авто: 7 ошибок перед сделкой'


def _sample_article():
    sections = {
        'Что учитывать перед покупкой': ('Перед покупкой подержанного автомобиля стоит заранее определить бюджет и список моделей, которые реально подходят под задачи. ') * 12,
        'Как проверить техническое состояние': ('Осмотр кузова, диагностика двигателя и проверка электроники помогают избежать скрытых поломок после сделки. ') * 12,
        'На что смотреть в документах': ('Сверка VIN-номера, истории регистрации и отсутствия ограничений снижает юридические риски покупателя. ') * 12,
        'Чек-лист перед сделкой': ('Полный чек-лист включает диагностику на подъёмнике, проверку истории обслуживания и тест-драйв по разным покрытиям. ') * 12,
        'Где можно потерять деньги или ошибиться': ('Главные ошибки покупателей связаны с игнорированием диагностики и доверием к устным заверениям продавца, что увеличивает риск переплаты. ') * 12,
        'Итог и следующий шаг': ('Решение стоит принимать только после независимой диагностики, а не под давлением сроков продавца. ') * 10,
    }
    article = '\n\n'.join(f'## {title}\n\n{body.strip()}' for title, body in sections.items())
    return {
        'headline': 'Как выбрать подержанный автомобиль без переплаты и рисков',
        'article_markdown': article,
        'fact_check': ['Проверить: VIN-номер и историю регистрации', 'Проверить: наличие ограничений и залогов', 'Проверить: реальный пробег по сервисной книге'],
        'source_urls': ['https://example.com/source-article'],
        'image_prompt': 'Photorealistic editorial automotive photography, natural daylight, mechanic inspecting a used car engine bay, 16:9',
    }


def test_quality_passes_on_a_well_formed_article():
    result = check_article(_sample_article(), require_ai_audit=False)
    assert result['ok'], result['problems']


def test_quality_rejects_thin_repetitive_draft():
    bad = {'headline': 'Нормальный заголовок для статьи об автомобиле', 'article_markdown': ('## Раздел\n\n' + 'слово ' * 200 + '\n\n') * 5, 'fact_check': [], 'source_urls': [], 'image_prompt': ''}
    result = check_article(bad, require_ai_audit=True)
    assert not result['ok']
    assert result['score'] < 90
    assert len(result['problems']) >= 5


def test_quota_shape():
    q = status()
    assert q['remaining'] >= 0 and q['limit'] >= q['used']
