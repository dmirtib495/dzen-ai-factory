def test_exact_image_set_reserves_five(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 5.2})
    reservations = []

    def reserve(amount):
        reservations.append(amount)
        return True

    monkeypatch.setattr(image_batch, 'reserve_neurons', reserve)
    assert image_batch._reserve_exact_set() == 5
    assert reservations == [cost * 5]


def test_exact_image_set_refuses_when_five_are_not_affordable(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 4.99})
    monkeypatch.setattr(image_batch, 'reserve_neurons', lambda amount: True)

    try:
        image_batch._reserve_exact_set()
    except RuntimeError as exc:
        assert 'обязательного набора из 5 изображений' in str(exc)
    else:
        raise AssertionError('Expected RuntimeError when five images are not affordable')


def test_exact_image_set_refuses_failed_atomic_reservation(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 6})
    monkeypatch.setattr(image_batch, 'reserve_neurons', lambda amount: False)

    try:
        image_batch._reserve_exact_set()
    except RuntimeError as exc:
        assert 'атомарно зарезервировать' in str(exc)
    else:
        raise AssertionError('Expected RuntimeError when atomic reservation loses a race')


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
