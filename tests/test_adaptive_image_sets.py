def test_adaptive_image_set_uses_largest_affordable_count(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 4.2})
    reservations = []

    def reserve(amount):
        reservations.append(amount)
        return True

    monkeypatch.setattr(image_batch, 'reserve_neurons', reserve)
    assert image_batch._reserve_adaptive_set() == 4
    assert reservations == [cost * 4]


def test_adaptive_image_set_steps_down_after_reservation_race(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 4.5})
    reservations = []

    def reserve(amount):
        reservations.append(amount)
        return len(reservations) == 2

    monkeypatch.setattr(image_batch, 'reserve_neurons', reserve)
    assert image_batch._reserve_adaptive_set() == 3
    assert reservations == [cost * 4, cost * 3]


def test_adaptive_image_set_refuses_less_than_three(monkeypatch):
    import image_batch

    cost = image_batch.FLUX_SCHNELL_NEURONS_PER_IMAGE
    monkeypatch.setattr(image_batch, 'image_quota_status', lambda: {'remaining': cost * 2.9})
    monkeypatch.setattr(image_batch, 'reserve_neurons', lambda amount: True)

    try:
        image_batch._reserve_adaptive_set()
    except RuntimeError as exc:
        assert 'минимального набора' in str(exc)
    else:
        raise AssertionError('Expected RuntimeError when fewer than three images are affordable')


def test_document_package_accepts_three_to_five_images():
    import document_packager

    assert document_packager.MIN_APPROVED_IMAGES == 3
    assert document_packager.MAX_APPROVED_IMAGES == 5
