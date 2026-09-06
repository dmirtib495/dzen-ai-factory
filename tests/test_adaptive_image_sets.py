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
