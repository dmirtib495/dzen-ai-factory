from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass

import requests

BASE_URL = "https://dzen.guru"
NICHE_URL = f"{BASE_URL}/channels/niche/avto"
DEFAULT_PERIOD_DAYS = 30
DEFAULT_TOP_CHANNELS = 8
DEFAULT_POSTS_PER_CHANNEL = 12

_HEADERS = {
    "User-Agent": "dzen-ai-factory/2.0 (+trend-signal; public analytics)",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}

_STOPWORDS = {
    "авто", "автомобиль", "автомобили", "машина", "машины", "новый", "новая", "новые",
    "россия", "россии", "российский", "сегодня", "почему", "когда", "какой", "какая", "какие",
    "этот", "эта", "эти", "своих", "своей", "против", "после", "перед", "через", "только",
    "можно", "нельзя", "стоит", "стали", "будет", "были", "есть", "если", "для", "или", "как",
    "что", "чем", "уже", "ещё", "очень", "самый", "самая", "снова", "рынок", "рынке",
    "car", "cars", "new", "the", "and", "with", "from", "why", "how",
}


@dataclass(frozen=True)
class DzenTrend:
    title: str
    url: str
    views: int
    channel_slug: str
    channel_title: str
    channel_views30days: int
    published_at: str = ""


def _get(url: str, *, timeout: int = 25) -> requests.Response:
    response = requests.get(url, headers=_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def parse_auto_channels(page_text: str) -> list[dict]:
    """Extract auto-channel ranking data from the server-rendered Next.js payload."""
    decoded = html.unescape(page_text).replace('\\"', '"').replace('\\n', ' ')
    pattern = re.compile(
        r'"slug":"(?P<slug>[A-Za-z0-9_.-]+)","title":"(?P<title>[^"]+)"'
        r'.{0,2400}?"views30days":(?P<views>\d+)',
        re.S,
    )
    found: dict[str, dict] = {}
    for match in pattern.finditer(decoded):
        slug = match.group("slug").strip()
        if not slug or slug in found:
            continue
        found[slug] = {
            "slug": slug,
            "title": match.group("title").replace("\\\\", "\\").strip(),
            "views30days": int(match.group("views")),
        }
    return sorted(found.values(), key=lambda x: x["views30days"], reverse=True)


def fetch_top_auto_channels(limit: int = DEFAULT_TOP_CHANNELS) -> list[dict]:
    channels = parse_auto_channels(_get(NICHE_URL).text)
    return channels[: max(1, int(limit))]


def fetch_channel_posts(slug: str, *, limit: int = DEFAULT_POSTS_PER_CHANNEL, period: int = DEFAULT_PERIOD_DAYS) -> list[dict]:
    url = f"{BASE_URL}/api/channels/{slug}/posts?offset=0&limit={int(limit)}&period={int(period)}"
    payload = _get(url).json()
    items = payload.get("items") if isinstance(payload, dict) else []
    return list(items or [])


def _is_article(item: dict) -> bool:
    url = str(item.get("url") or "")
    fmt = str(item.get("format") or item.get("type") or "").lower()
    return "/a/" in url and fmt not in {"gif", "video", "short", "shorts"}


def fetch_auto_trends(
    *,
    top_channels: int = DEFAULT_TOP_CHANNELS,
    posts_per_channel: int = DEFAULT_POSTS_PER_CHANNEL,
    period: int = DEFAULT_PERIOD_DAYS,
    limit: int = 60,
) -> list[DzenTrend]:
    """Return high-view article topics from the most-viewed public Dzen auto channels.

    dzen.guru is used only as a popularity signal. The returned Dzen URL must not
    be treated as factual evidence for an article because dzen.ru itself is not
    reliably readable from GitHub runners.
    """
    trends: list[DzenTrend] = []
    seen_urls: set[str] = set()
    for channel in fetch_top_auto_channels(top_channels):
        try:
            posts = fetch_channel_posts(channel["slug"], limit=posts_per_channel, period=period)
        except Exception:
            continue
        for item in posts:
            if not _is_article(item):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                views = max(0, int(item.get("views") or 0))
            except (TypeError, ValueError):
                views = 0
            trends.append(DzenTrend(
                title=title,
                url=url,
                views=views,
                channel_slug=str(channel["slug"]),
                channel_title=str(channel["title"]),
                channel_views30days=int(channel["views30days"]),
                published_at=str(item.get("publishedAt") or item.get("published_at") or ""),
            ))
    trends.sort(key=lambda x: (x.views, x.channel_views30days), reverse=True)
    return trends[: max(1, int(limit))]


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and not w.isdigit()}


def trend_relevance(topic_title: str, trend_title: str) -> float:
    """Lexical/entity similarity, intentionally conservative to avoid false trend matches."""
    a, b = _tokens(topic_title), _tokens(trend_title)
    if not a or not b:
        return 0.0
    common = a & b
    if not common:
        return 0.0
    # One shared specific brand/model token is useful, but two or more are a
    # much stronger indication that both headlines describe the same topic.
    containment = len(common) / max(1, min(len(a), len(b)))
    jaccard = len(common) / max(1, len(a | b))
    return min(1.0, 0.7 * containment + 0.3 * jaccard)


def best_trend_match(topic_title: str, trends: list[DzenTrend]) -> tuple[DzenTrend | None, float, float]:
    best: DzenTrend | None = None
    best_rel = 0.0
    for trend in trends:
        rel = trend_relevance(topic_title, trend.title)
        if rel > best_rel:
            best, best_rel = trend, rel
    if best is None or best_rel < 0.20:
        return None, 0.0, 0.0
    # Popularity bonus is bounded so trend demand improves ordering but never
    # overwhelms the existing automotive/editorial quality score by itself.
    popularity = min(1.0, math.log10(max(best.views, 1) + 1) / 5.0)
    bonus = round(45.0 * best_rel * popularity, 2)
    return best, best_rel, bonus
