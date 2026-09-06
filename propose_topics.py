from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

from analytics import recommended_categories
from cloud_sync import query
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_MODEL
from topic_hunter import collect_topics
from topic_scorer import rank

CHOICE_COUNT = 5


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zа-я0-9]+", (text or "").lower())
    stop = {
        "авто", "автомобиль", "машина", "новый", "новая", "новые", "рынок", "россия",
        "купить", "стоит", "цена", "обзор", "тест", "года", "год", "что", "как", "для",
        "the", "new", "car", "review", "price", "with", "from",
    }
    return {w for w in words if len(w) >= 3 and w not in stop}


def _too_similar(title: str, previous: list[str]) -> bool:
    current = _tokens(title)
    if not current:
        return False
    for old in previous:
        other = _tokens(old)
        if not other:
            continue
        overlap = current & other
        union = current | other
        if len(overlap) >= 3 and len(overlap) / max(1, len(union)) >= 0.34:
            return True
        if len(overlap) >= 2 and any(any(ch.isdigit() for ch in token) for token in overlap):
            return True
    return False


def _history() -> list[str]:
    result = query(
        """
        SELECT headline AS title FROM articles
        UNION ALL
        SELECT title FROM topic_proposals
        WHERE created_at >= datetime('now','-30 day')
        ORDER BY title
        """
    ) or {}
    return [str(x.get("title") or "") for x in result.get("results", []) if x.get("title")]


def _clean_vehicle_name(title: str) -> str:
    text = re.sub(r",?\s*20\d{2}\s*г\.?\s*$", "", (title or "").strip(), flags=re.I)
    return text.strip(" ,.-") or (title or "Автомобиль").strip()


def _source_entry(item: dict) -> dict:
    return {
        "title": str(item.get("title") or ""),
        "url": str(item.get("link") or ""),
        "source": str(item.get("source") or ""),
        "summary": str(item.get("summary") or ""),
    }


def _bundle_summary(editorial_brief: str, items: list[dict]) -> str:
    return json.dumps(
        {
            "editorial_brief": editorial_brief,
            "sources": [_source_entry(x) for x in items],
        },
        ensure_ascii=False,
    )


def _derived(title: str, fmt: str, items: list[dict], bonus: float = 0.0) -> dict:
    base_score = sum(float(x.get("score") or 0) for x in items) / max(1, len(items))
    trend = max(items, key=lambda x: int(x.get("trend_views") or 0), default={})
    brief_by_format = {
        "comparison": (
            "Сделай честное практическое сравнение нескольких автомобилей. Сравнивай только те характеристики, "
            "которые подтверждаются приложенными источниками; не выдумывай комплектации, цены и типичные поломки. "
            "Главный вопрос — кому какой вариант подходит и почему."
        ),
        "practical": (
            "Сделай практический материал для человека, который рассматривает покупку этой машины с пробегом. "
            "Отделяй подтверждённые источником факты от универсальных советов по осмотру автомобиля. "
            "Не приписывай модели неисправности или расходы, которых нет в источнике."
        ),
        "market": (
            "Сделай широкую редакционную подборку по нескольким свежим автомобильным темам. "
            "Покажи различия сценариев покупки и целевой аудитории. Все конкретные факты и цифры привязывай "
            "к соответствующему источнику; не превращай материал в список несвязанных новостей."
        ),
    }
    item = dict(items[0])
    item.update({
        "title": title,
        "format": fmt,
        "summary": _bundle_summary(brief_by_format[fmt], items),
        "score": base_score + bonus,
        "trend_title": str(trend.get("trend_title") or ""),
        "trend_views": int(trend.get("trend_views") or 0),
        "trend_channel": str(trend.get("trend_channel") or ""),
    })
    return item


def build_diverse_choices(candidates: list[dict], history: list[str] | None = None) -> list[dict]:
    """Return five choices with mandatory editorial-format diversity."""
    history = list(history or [])
    fresh: list[dict] = []
    seen = list(history)
    for item in candidates:
        title = str(item.get("title") or "")
        if not title or _too_similar(title, seen):
            continue
        fresh.append(dict(item))
        seen.append(title)
        if len(fresh) >= 12:
            break
    if len(fresh) < 3:
        raise RuntimeError(f"Not enough fresh source topics for diverse choice set: {len(fresh)}")

    choices: list[dict] = []
    # Two strong single-car stories.
    for base in fresh[:2]:
        direct = dict(base)
        direct["format"] = "single"
        choices.append(direct)

    # One comparison built from several independent source items.
    compare_items = fresh[2:5]
    if len(compare_items) < 3:
        compare_items += fresh[: 3 - len(compare_items)]
    compare_names = [_clean_vehicle_name(x.get("title", "")) for x in compare_items]
    choices.append(_derived(
        f"Что выбрать: {compare_names[0]}, {compare_names[1]} или {compare_names[2]} — сравниваем варианты для реальной покупки",
        "comparison",
        compare_items,
        bonus=4.0,
    ))

    # One practical ownership/buying angle.
    practical = fresh[5] if len(fresh) > 5 else fresh[-1]
    practical_name = _clean_vehicle_name(practical.get("title", ""))
    choices.append(_derived(
        f"{practical_name} с пробегом: что проверить перед покупкой и кому такой автомобиль подойдёт",
        "practical",
        [practical],
        bonus=3.0,
    ))

    # One broad selection/market story using several sources, not one specific car.
    market_items = fresh[6:11] if len(fresh) >= 11 else fresh[:5]
    market_names = [_clean_vehicle_name(x.get("title", "")) for x in market_items[:5]]
    choices.append(_derived(
        "Пять интересных автомобилей из свежей повестки: что выбрать под разные задачи и бюджет",
        "market",
        market_items[:5],
        bonus=2.0,
    ))

    # Final history guard for derived titles. If a synthesized angle was used recently,
    # keep the format but rotate its source base and wording instead of falling back to five single-car topics.
    final: list[dict] = []
    final_seen = list(history)
    labels = {"single": "🚗 Модель", "comparison": "⚖️ Сравнение", "practical": "🔧 Практика", "market": "📊 Подборка"}
    for item in choices:
        title = str(item.get("title") or "")
        if _too_similar(title, final_seen) and item.get("format") != "single":
            title = f"{title} — свежий разбор"
            item["title"] = title
        item["format_label"] = labels.get(str(item.get("format")), "🚗 Тема")
        final.append(item)
        final_seen.append(title)
    return final[:CHOICE_COUNT]



def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
    try:
        data = json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise ValueError("YandexGPT did not return JSON")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("YandexGPT response is not an object")
    return data


def _yandex_json(prompt: str, max_tokens: int = 7000) -> dict:
    if not (YANDEX_API_KEY and YANDEX_FOLDER_ID):
        raise RuntimeError("YandexGPT is not configured for editorial topic analysis")
    response = requests.post(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        headers={"Authorization": f"Api-Key {YANDEX_API_KEY}", "Content-Type": "application/json"},
        json={
            "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
            "completionOptions": {"stream": False, "temperature": 0.15, "maxTokens": max_tokens},
            "messages": [
                {
                    "role": "system",
                    "text": (
                        "Ты главный редактор автомобильного медиа. Принимай решения по читательской "
                        "пользе, намерению аудитории, актуальности, доказательной базе и разнообразию "
                        "форматов. Не используй простое совпадение слов или названий моделей как главный критерий. "
                        "Верни только валидный JSON."
                    ),
                },
                {"role": "user", "text": prompt},
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    return _extract_json(response.json()["result"]["alternatives"][0]["message"]["text"])


def _custom_topics() -> list[dict]:
    result = query(
        """
        SELECT id,title,summary,created_at
        FROM topic_proposals
        WHERE source IN ('Тема, предложенная пользователем','Источник, указанный пользователем')
        ORDER BY id
        """
    ) or {}
    return [dict(row) for row in result.get("results", [])]


def _editorial_profile(custom: list[dict]) -> dict | None:
    if len(custom) < 10:
        return None
    max_id = max(int(x.get("id") or 0) for x in custom)
    cached = query("SELECT value FROM settings WHERE key='custom_topic_editorial_profile'") or {}
    rows = cached.get("results", [])
    if rows:
        try:
            value = json.loads(str(rows[0].get("value") or "{}"))
            if int(value.get("source_count") or 0) == len(custom) and int(value.get("source_max_id") or 0) == max_id:
                return value
        except Exception:
            pass

    material = [
        {"id": int(x.get("id") or 0), "topic": str(x.get("title") or ""), "context": str(x.get("summary") or "")[:700]}
        for x in custom[-50:]
    ]
    prompt = f"""Проанализируй историю тем, которые владелец канала предложил лично.
Это не задача поиска похожих марок или слов. Выведи устойчивую редакционную стратегию:
- какие решения и проблемы владельцев автомобилей интересуют аудиторию;
- какие читательские сценарии, риски, конфликты и вопросы выбора повторяются;
- какие форматы и углы подачи предпочтительны;
- какие темы нельзя предлагать только из-за поверхностной схожести;
- как соединять этот профиль со свежими сигналами Дзена и реальными источниками.

ТЕМЫ ВЛАДЕЛЬЦА:
{json.dumps(material, ensure_ascii=False)}

Верни JSON:
{{
  "audience_needs": ["..."],
  "editorial_pillars": ["..."],
  "decision_situations": ["..."],
  "preferred_formats": ["..."],
  "commercial_signals": ["..."],
  "avoid_patterns": ["..."],
  "selection_rules": ["..."]
}}"""
    profile = _yandex_json(prompt, max_tokens=4500)
    profile["source_count"] = len(custom)
    profile["source_max_id"] = max_id
    now = datetime.now(timezone.utc).isoformat()
    query(
        """
        INSERT INTO settings(key,value,updated_at) VALUES('custom_topic_editorial_profile',?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
        """,
        [json.dumps(profile, ensure_ascii=False), now],
    )
    return profile


def _professional_choices(candidates: list[dict], history: list[str], profile: dict) -> list[dict]:
    pool = []
    for idx, item in enumerate(candidates[:30]):
        pool.append({
            "index": idx,
            "title": str(item.get("title") or ""),
            "source": str(item.get("source") or ""),
            "summary": str(item.get("summary") or "")[:600],
            "score": float(item.get("score") or 0),
            "dzen_signal": {
                "title": str(item.get("trend_title") or ""),
                "views": int(item.get("trend_views") or 0),
                "channel": str(item.get("trend_channel") or ""),
            },
        })
    prompt = f"""Выбери пять новых тем для автомобильного канала как профессиональный главный редактор.

РЕДАКЦИОННЫЙ ПРОФИЛЬ, построенный минимум по 10 личным темам владельца:
{json.dumps(profile, ensure_ascii=False)}

СВЕЖИЕ ПРОВЕРЯЕМЫЕ ИСТОЧНИКИ И СИГНАЛЫ ДЗЕНА:
{json.dumps(pool, ensure_ascii=False)}

НЕДАВНИЕ ТЕМЫ, которые нельзя повторять:
{json.dumps(history[-80:], ensure_ascii=False)}

Правила:
1. Сначала оцени читательское намерение, практическую пользу, риск переплаты/ошибки, актуальность и силу источников.
2. Совпадение марки, модели или отдельных слов с историей владельца само по себе ничего не доказывает.
3. Не объединяй несопоставимые объекты: рыночную статистику нельзя ставить как автомобиль в сравнении моделей.
4. Нужны разные форматы: конкретная модель, практический разбор, честное сравнение сопоставимых машин, рыночная/правовая тема и одна сильная тема по редакционному профилю.
5. Каждый вариант обязан опираться только на указанные source_indices.
6. Заголовки должны быть естественными, конкретными и без дешёвого кликбейта.
7. Не копируй личные темы владельца; развивай их редакционную логику на свежем материале.

Верни JSON:
{{
  "choices": [
    {{
      "title": "...",
      "format": "single|practical|comparison|market|editorial",
      "source_indices": [0],
      "editorial_brief": "...",
      "rationale": "почему тема соответствует профилю и свежему спросу"
    }}
  ]
}}
Ровно пять choices."""
    result = _yandex_json(prompt)
    raw_choices = result.get("choices")
    if not isinstance(raw_choices, list) or len(raw_choices) != 5:
        raise ValueError("Editorial selector did not return exactly five choices")
    labels = {
        "single": "🚗 Модель", "practical": "🔧 Практика", "comparison": "⚖️ Сравнение",
        "market": "📊 Рынок", "editorial": "🎯 По твоим темам",
    }
    final = []
    for position, choice in enumerate(raw_choices):
        if not isinstance(choice, dict):
            raise ValueError("Invalid editorial choice")
        indices = []
        for value in choice.get("source_indices") or []:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(candidates) and idx not in indices:
                indices.append(idx)
        if not indices:
            raise ValueError("Editorial choice has no valid source")
        items = [candidates[idx] for idx in indices[:5]]
        item = dict(items[0])
        fmt = str(choice.get("format") or "editorial")
        brief = str(choice.get("editorial_brief") or "").strip()
        rationale = str(choice.get("rationale") or "").strip()
        item.update({
            "title": str(choice.get("title") or item.get("title") or "").strip(),
            "format": fmt,
            "format_label": labels.get(fmt, "🎯 По твоим темам"),
            "summary": _bundle_summary(brief + ("\n\nРедакторская причина выбора: " + rationale if rationale else ""), items),
            "score": sum(float(x.get("score") or 0) for x in items) / len(items) + (5 - position),
            "preference_rationale": rationale,
            "profile_source_count": int(profile.get("source_count") or 0),
        })
        final.append(item)
    return final

def _send_choices(group_id: str, choices: list[dict], profile_count: int = 0) -> int:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не настроены")
    lines = [
        "🧭 Выбери тему для следующей статьи",
        "",
        "Теперь варианты специально разных форматов. Фабрика НЕ начнёт писать статью, пока ты не выберешь один:",
        *( [f"🎯 Учтён редакционный профиль по {profile_count} твоим темам.", ""] if profile_count >= 10 else [""] ),
    ]
    keyboard = []
    for idx, item in enumerate(choices, 1):
        label = str(item.get("format_label") or "🚗 Тема")
        lines.append(f"{idx}. {label} · {item['title']}")
        if item.get("trend_views"):
            lines.append(f"   Сигнал Дзена: {int(item['trend_views']):,} просмотров".replace(",", " "))
        lines.append(f"   Рейтинг: {float(item.get('score', 0)):.1f}")
        lines.append("")
        keyboard.append([{"text": f"{idx}. {label} · {item['title'][:38]}", "callback_data": f"topic_pick:{item['proposal_id']}"}])
    keyboard.append([{"text": "🔄 Подобрать другие темы", "callback_data": f"topic_refresh:{group_id}"}])
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "\n".join(lines)[:4096],
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": keyboard},
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(str(data))
    return int((data.get("result") or {}).get("message_id") or 0)


def main() -> None:
    history = _history()
    candidates = rank(collect_topics(80))
    preferred = recommended_categories()
    candidates = sorted(
        candidates,
        key=lambda t: (
            preferred.index(t.get("category", "")) if t.get("category", "") in preferred else 99,
            -float(t.get("score", 0)),
        ),
    )
    custom = _custom_topics()
    profile = None
    if len(custom) >= 10:
        try:
            profile = _editorial_profile(custom)
            choices = _professional_choices(candidates, history, profile)
            print("CUSTOM_EDITORIAL_PROFILE_APPLIED", json.dumps({
                "source_count": len(custom),
                "pillars": (profile or {}).get("editorial_pillars", []),
            }, ensure_ascii=False))
        except Exception as exc:
            print(f"CUSTOM_EDITORIAL_PROFILE_FALLBACK reason={exc}")
            choices = build_diverse_choices(candidates, history)
    else:
        choices = build_diverse_choices(candidates, history)

    now = datetime.now(timezone.utc).isoformat()
    group_id = uuid.uuid4().hex[:16]
    query(
        "INSERT INTO topic_proposal_groups(id,status,selected_proposal_id,telegram_message_id,created_at,updated_at) VALUES(?, 'pending', NULL, NULL, ?, ?)",
        [group_id, now, now],
    )

    stored: list[dict] = []
    for pos, item in enumerate(choices, 1):
        result = query(
            """
            INSERT INTO topic_proposals(
                group_id,position,title,link,source,summary,score,trend_title,trend_views,trend_channel,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?, 'pending', ?, ?)
            RETURNING id
            """,
            [
                group_id, pos, str(item.get("title") or ""), str(item.get("link") or ""),
                str(item.get("source") or ""), str(item.get("summary") or ""), float(item.get("score") or 0),
                str(item.get("trend_title") or ""), int(item.get("trend_views") or 0),
                str(item.get("trend_channel") or ""), now, now,
            ],
        ) or {}
        rows = result.get("results", [])
        if not rows:
            raise RuntimeError("D1 did not return topic proposal id")
        item["proposal_id"] = int(rows[0]["id"])
        stored.append(item)

    message_id = _send_choices(group_id, stored, len(custom) if profile else 0)
    query(
        "UPDATE topic_proposal_groups SET telegram_message_id=?,updated_at=? WHERE id=?",
        [message_id, datetime.now(timezone.utc).isoformat(), group_id],
    )
    print("TOPIC_CHOICES_SENT", json.dumps({
        "group_id": group_id,
        "message_id": message_id,
        "choices": [{"id": x["proposal_id"], "format": x.get("format"), "title": x["title"]} for x in stored],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
