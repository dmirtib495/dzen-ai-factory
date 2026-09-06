def test_adaptive_image_set_reserves_five_when_affordable(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 5.2})
    reservations = []
    monkeypatch.setattr(image_batch, 'reserve_neurons', lambda amount: reservations.append(amount) or True)

    assert image_batch._reserve_adaptive_set() == 5
    assert reservations == [cost * 5]


def test_adaptive_image_set_uses_four_when_only_four_are_affordable(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 4.99})
    reservations = []
    monkeypatch.setattr(image_batch, 'reserve_neurons', lambda amount: reservations.append(amount) or True)

    assert image_batch._reserve_adaptive_set() == 4
    assert reservations == [cost * 4]


def test_adaptive_image_set_refuses_when_three_are_not_affordable(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 2.99})
    monkeypatch.setattr(image_batch, 'reserve_neurons', lambda amount: True)

    try:
        image_batch._reserve_adaptive_set()
    except RuntimeError as exc:
        assert 'минимального набора из 3 изображений' in str(exc)
    else:
        raise AssertionError('Expected RuntimeError when three images are not affordable')


def test_adaptive_image_set_retries_smaller_atomic_reservation(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 5})
    reservations = []

    def reserve(amount):
        reservations.append(amount)
        return amount == cost * 4

    monkeypatch.setattr(image_batch, 'reserve_neurons', reserve)

    assert image_batch._reserve_adaptive_set() == 4
    assert reservations == [cost * 5, cost * 4]


def test_document_package_accepts_three_to_five_images():
    import document_packager

    assert document_packager.MIN_APPROVED_IMAGES == 3
    assert document_packager.MAX_APPROVED_IMAGES == 5


def test_comparison_prompts_balance_both_vehicle_models():
    from image_generator import editorial_prompts

    prompts = editorial_prompts(
        'Honda Freed или Toyota Probox: что выбрать для практичной покупки',
        5,
        article_markdown=(
            '## Honda Freed\nHonda Freed рассматривается как первый вариант.\n\n'
            '## Toyota Probox\nToyota Probox рассматривается как второй вариант.\n\n'
            '## Сравнение\nСравниваем Honda Freed и Toyota Probox.'
        ),
        category='Сравнения',
    )

    assert len(prompts) == 5
    assert all('Honda Freed' in prompt or 'Toyota Probox' in prompt for prompt in prompts)
    assert sum('Honda Freed' in prompt and 'Toyota Probox' in prompt for prompt in prompts) >= 3
    assert 'Honda Freed' in prompts[1] and 'No Toyota Probox' in prompts[1]
    assert 'Toyota Probox' in prompts[2] and 'No Honda Freed' in prompts[2]
    assert any('Do not merge' in prompt or 'No hybridized' in prompt for prompt in prompts)


def test_single_vehicle_prompts_do_not_invent_comparison():
    from image_generator import editorial_prompts

    prompts = editorial_prompts(
        'Mitsubishi Pajero с пробегом: что проверить',
        5,
        article_markdown='Практический осмотр Mitsubishi Pajero перед покупкой.',
        category='Стоит ли брать',
    )

    assert len(prompts) == 5
    assert all('Mitsubishi Pajero' in prompt for prompt in prompts)
    assert not any('two clearly separate real vehicles' in prompt for prompt in prompts)


def test_generic_ev_topic_uses_one_tesla_in_different_situations():
    from image_generator import editorial_prompts

    prompts = editorial_prompts(
        'Владение электромобилем в Москве и поездки на море',
        5,
        article_markdown=(
            '## Городская зарядка\nПрактика зарядки электромобиля.\n\n'
            '## Зима\nЭксплуатация зимой.\n\n'
            '## Трасса\nПодготовка дальней поездки.'
        ),
        category='Авто-технологии',
    )

    assert len(prompts) == 5
    assert all('Tesla Model 3' in prompt for prompt in prompts)
    assert all('pearl white' in prompt for prompt in prompts)
    assert any('Moscow' in prompt and 'charging station' in prompt for prompt in prompts)
    assert any('snowy Moscow' in prompt for prompt in prompts)
    assert any('motorway charging stop' in prompt for prompt in prompts)
    assert any('Black Sea' in prompt for prompt in prompts)
    assert any('service bay' in prompt for prompt in prompts)


def test_semantic_visual_plan_binds_each_prompt_to_article_section(monkeypatch):
    import image_generator

    plan = [
        {'section_index': 1, 'section_heading': 'Зарядка во дворе', 'prompt': 'A documentary ownership scene beside a residential charging point in Moscow, with the driver connecting the cable carefully.'},
        {'section_index': 2, 'section_heading': 'Зимняя эксплуатация', 'prompt': 'A realistic cold-weather ownership scene in a snowy Moscow parking area, showing careful preparation before departure.'},
        {'section_index': 3, 'section_heading': 'Поездка по трассе', 'prompt': 'A practical motorway rest-stop scene during an intercity journey, with the car safely parked near a charging bay.'},
    ]
    captured = {}

    def fake_plan(headline, article_markdown, **kwargs):
        captured['headline'] = headline
        captured['article'] = article_markdown
        captured.update(kwargs)
        return plan

    monkeypatch.setattr(image_generator, '_yandex_visual_plan', fake_plan)
    article = (
        '## Зарядка во дворе\nПодготовка городской зарядки.\n\n'
        '## Зимняя эксплуатация\nПоездки в мороз.\n\n'
        '## Поездка по трассе\nМаршрут между городами.'
    )
    prompts = image_generator.editorial_prompts(
        'Электромобиль в Москве: город, зима и трасса',
        3,
        article_markdown=article,
        category='Авто-технологии',
    )

    assert captured['article'] == article
    assert captured['count'] == 3
    assert all('Tesla Model 3' in prompt for prompt in prompts)
    assert 'Зарядка во дворе' in prompts[0]
    assert 'Зимняя эксплуатация' in prompts[1]
    assert 'Поездка по трассе' in prompts[2]
    assert len(set(prompts)) == 3
