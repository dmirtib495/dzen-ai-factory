import json
import logging
import re
from typing import Any

import requests
from openai import OpenAI

from config import (
    CHANNEL_NAME,
    MAX_ARTICLE_WORDS,
    MIN_ARTICLE_WORDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_DAILY_LIMIT,
    OPENROUTER_MODEL,
    YANDEX_API_KEY,
    YANDEX_FOLDER_ID,
    YANDEX_MODEL,
)
from quota import reserve

log = logging.getLogger(__name__)

SYSTEM = f'''Ты главный редактор автомобильного канала «{CHANNEL_NAME}». Пиши оригинальные полезные материалы на русском.
Не копируй источники и не выдумывай факты, цены, характеристики, законы, цитаты или результаты тестов.
Если точное значение не подтверждено входными данными, пометь его как «нужно проверить».
Не используй абсолютные обещания и кликбейт. Даже новость превращай в практический разбор для владельца или покупателя.'''


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [text for item in value if (text := _as_text(item))]


def _extract(value: Any):
    if isinstance(value, dict):
        return value
    value = _as_text(value)
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S)
    try:
        return json.loads(value)
    except Exception:
        match = re.search(r"\{.*\}", value, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _normalize(data: Any, provider: str, model: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError("AI вернул некорректную структуру")
    headline = _as_text(data.get("headline"))
    headlines = _as_string_list(data.get("headlines"))
    if headline and headline not in headlines:
        headlines.insert(0, headline)
    if not headline and headlines:
        headline = headlines[0]
    article = _as_text(data.get("article_markdown"))
    if not headline or not article:
        raise ValueError("AI не вернул обязательные поля статьи")
    category = _as_text(data.get("category"))
    allowed = {"Что купить", "Стоит ли брать", "Экономия", "Сравнения", "Авто-технологии"}
    if category not in allowed:
        category = "Стоит ли брать"
    try:
        commercial = max(0, min(10, int(float(data.get("commercial_intent", 5)))))
    except (TypeError, ValueError):
        commercial = 5
    return {
        "headline": headline,
        "headlines": headlines[:5] or [headline],
        "category": category,
        "article_markdown": article,
        "fact_check": _as_string_list(data.get("fact_check")),
        "image_prompt": _as_text(data.get("image_prompt")),
        "source_urls": _as_string_list(data.get("source_urls")),
        "commercial_intent": commercial,
        "ai_provider": provider,
        "ai_model": model,
        "ai_stages": [f"{provider}:{model}"],
    }


def _article_prompt(topic: dict) -> str:
    return f'''Источник темы: {_as_text(topic.get('source'))}
Заголовок исходной темы: {_as_text(topic.get('title'))}
Ссылка: {_as_text(topic.get('link'))}
Описание: {_as_text(topic.get('summary'))}

Сделай самостоятельный материал {MIN_ARTICLE_WORDS}–{MAX_ARTICLE_WORDS} слов. Нужны лид, 5–8 подзаголовков, практические пункты и честный вывод.
Предложи 5 заголовков. Категория только из: Что купить; Стоит ли брать; Экономия; Сравнения; Авто-технологии.
Верни ТОЛЬКО JSON: headline, headlines, category, article_markdown, fact_check, image_prompt, source_urls, commercial_intent.'''


def _openrouter_draft(topic: dict) -> dict:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")
    if not reserve():
        raise RuntimeError(f"Дневной лимит OpenRouter исчерпан ({OPENROUTER_DAILY_LIMIT})")
    client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1", timeout=120, max_retries=1)
    models = []
    for model in (OPENROUTER_MODEL, "openrouter/free"):
        if model and model not in models:
            models.append(model)
    errors = []
    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": _article_prompt(topic)}],
                temperature=0.5,
            )
            data = _extract(response.choices[0].message.content or "")
            return _normalize(data, "OpenRouter", model)
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("OpenRouter недоступен: " + " | ".join(errors))


def _editor_prompt(data: dict, editor_name: str) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f'''Ты {editor_name} автомобильного медиа. Проверь русский язык, логику, полезность, отсутствие выдуманных фактов и рекламных обещаний.
Не добавляй новые неподтвержденные факты. Сохрани источники. Улучши материал только если это действительно нужно.
Верни ТОЛЬКО JSON с теми же полями: headline, headlines, category, article_markdown, fact_check, image_prompt, source_urls, commercial_intent.
Материал: {payload}'''


def _yandex_edit(data: dict) -> dict:
    if not (YANDEX_API_KEY and YANDEX_FOLDER_ID):
        return data
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    body = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
        "completionOptions": {"stream": False, "temperature": 0.25, "maxTokens": 8000},
        "messages": [{"role": "system", "text": SYSTEM}, {"role": "user", "text": _editor_prompt(data, "редактор Yandex AI")}],
    }
    response = requests.post(url, headers={"Authorization": f"Api-Key {YANDEX_API_KEY}", "Content-Type": "application/json"}, json=body, timeout=120)
    response.raise_for_status()
    raw = response.json()["result"]["alternatives"][0]["message"]["text"]
    edited = _normalize(_extract(raw), "Yandex AI", YANDEX_MODEL)
    edited["ai_stages"] = data.get("ai_stages", []) + [f"Yandex AI:{YANDEX_MODEL}"]
    return edited


def _openai_edit(data: dict) -> dict:
    if not OPENAI_API_KEY:
        return data
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=120, max_retries=1)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": _editor_prompt(data, "финальный редактор OpenAI")}],
    )
    edited = _normalize(_extract(response.choices[0].message.content or ""), "OpenAI", OPENAI_MODEL)
    edited["ai_stages"] = data.get("ai_stages", []) + [f"OpenAI:{OPENAI_MODEL}"]
    return edited


def generate_article(topic):
    data = _openrouter_draft(topic)
    for name, stage in (("Yandex AI", _yandex_edit), ("OpenAI", _openai_edit)):
        try:
            data = stage(data)
        except Exception as exc:
            log.warning("Optional editor %s skipped: %s", name, exc)
    return data
