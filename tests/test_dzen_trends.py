from dzen_trends import DzenTrend, best_trend_match, parse_auto_channels, trend_relevance


def test_parse_auto_channels_sorts_by_views():
    page = r'''
    <script>self.__next_f.push([1,"{\"slug\":\"small-auto\",\"title\":\"Малый авто\",\"subscribers\":100,\"views30days\":12000,\"publications30days\":20}"])</script>
    <script>self.__next_f.push([1,"{\"slug\":\"big-auto\",\"title\":\"Большой авто\",\"subscribers\":200,\"views30days\":950000,\"publications30days\":30}"])</script>
    '''
    rows = parse_auto_channels(page)
    assert [x['slug'] for x in rows] == ['big-auto', 'small-auto']
    assert rows[0]['views30days'] == 950000


def test_trend_relevance_requires_specific_overlap():
    assert trend_relevance('Subaru Forester: что проверить перед покупкой', 'Subaru Forester активно везут в Россию') > 0.2
    assert trend_relevance('BMW X5: расходы на обслуживание', 'Почему на АЗС есть дизельное топливо') == 0.0


def test_best_trend_match_returns_bounded_bonus():
    trends = [
        DzenTrend(
            title='Subaru Forester активно везут в Россию',
            url='https://dzen.ru/a/example',
            views=27234,
            channel_slug='autovybor',
            channel_title='Автовыбор',
            channel_views30days=1000000,
        )
    ]
    trend, relevance, bonus = best_trend_match('Subaru Forester: что важно проверить перед покупкой', trends)
    assert trend is trends[0]
    assert relevance >= 0.2
    assert 0 < bonus <= 45
