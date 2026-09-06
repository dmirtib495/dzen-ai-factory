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
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
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
        # Repeating the same make+model is undesirable even when the article angle differs.
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


def _send_choices(group_id: str, choices: list[dict]) -> int:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не настроены")
    lines = [
        "🧭 Выбери тему для следующей статьи",
        "",
        "Фабрика НЕ начнёт писать статью, пока ты не выберешь один вариант:",
        "",
    ]
    keyboard = []
    for idx, item in enumerate(choices, 1):
        lines.append(f"{idx}. {item['title']}")
        if item.get("trend_views"):
            lines.append(f"   Сигнал Дзена: {int(item['trend_views']):,} просмотров".replace(",", " "))
        lines.append(f"   Рейтинг: {float(item.get('score', 0)):.1f}")
        lines.append("")
        keyboard.append([{"text": f"{idx}. {item['title'][:48]}", "callback_data": f"topic_pick:{item['proposal_id']}"}])
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
    candidates = rank(collect_topics(60))
    preferred = recommended_categories()
    candidates = sorted(
        candidates,
        key=lambda t: (
            preferred.index(t.get("category", "")) if t.get("category", "") in preferred else 99,
            -float(t.get("score", 0)),
        ),
    )

    choices: list[dict] = []
    seen_titles = list(history)
    for item in candidates:
        if _too_similar(str(item.get("title") or ""), seen_titles):
            continue
        choices.append(dict(item))
        seen_titles.append(str(item.get("title") or ""))
        if len(choices) >= CHOICE_COUNT:
            break
    if len(choices) < 3:
        raise SystemExit(f"Not enough fresh distinct topic choices: {len(choices)}")

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

    message_id = _send_choices(group_id, stored)
    query(
        "UPDATE topic_proposal_groups SET telegram_message_id=?,updated_at=? WHERE id=?",
        [message_id, datetime.now(timezone.utc).isoformat(), group_id],
    )
    print("TOPIC_CHOICES_SENT", json.dumps({
        "group_id": group_id,
        "message_id": message_id,
        "choices": [{"id": x["proposal_id"], "title": x["title"]} for x in stored],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
