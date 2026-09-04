import json
import logging
import re
import time
from typing import Any

from openai import OpenAI

from config import (
    CHANNEL_NAME,
    MAX_ARTICLE_WORDS,
    MIN_ARTICLE_WORDS,
    OPENROUTER_API_KEY,
    OPENROUTER_DAILY_LIMIT,
    OPENROUTER_MODEL,
)
from quota import reserve

log = logging.getLogger(__name__)

SYSTEM = f'''Ты главный редактор автомобильного канала «{CHANNEL_NAME}». Пиши оригинальные полезные материалы на русском.
Не копируй источники и не выдумывай факты, цены, характеристики, законы, цитаты или результаты тестов.
Если точное значение не подтверждено входными данными, пометь его как «нужно проверить».
Не используй абсолютные обещания и кликбейт. Даже новость превращай в практический разбор для владельца или покупателя.'''

# Free-first routing. Specific DeepSeek free endpoints are tried before the
# general OpenRouter free router. The general router is the final safety net.
MODEL_CHAIN = [
    "deepseek/deepseek-v4-flash:free",
    "deepseek/deepseek-chat-v3.1:free",
    "deepseek/deepseek-chat:free",
    OPENROUTER_MODEL,
    "openrouter/free",
]


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
    result = []
    for item in value:
        text = _as_text(item)
        if text:
            result.append(text)
    return result


def _extract(value: Any):
    if isinstance(value, dict):
        return value
    value = _as_text(value).strip()
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


def _normalize(data: Any, model: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError("AI вернул JSON, но корневой объект не является словарём")

    headline = _as_text(data.get("headline"))
    article = _as_text(data.get("article_markdown"))
    category = _as_text(data.get("category")) or "Стоит ли брать"
    headlines = _as_string_list(data.get("headlines"))

    if headline and headline not in headlines:
        headlines.insert(0, headline)
    if not headline and headlines:
        headline = headlines[0]
    if not headline:
        raise ValueError("AI не вернул заголовок")
    if not article:
        raise ValueError("AI не вернул текст статьи")

    allowed_categories = {
        "Что купить",
        "Стоит ли брать",
        "Экономия",
        "Сравнения",
        "Авто-технологии",
    }
    if category not in allowed_categories:
        category = "Стоит ли брать"

    commercial = data.get("commercial_intent", 5)
    try:
        commercial = max(0, min(10, int(float(commercial))))
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
        "ai_provider": "OpenRouter",
        "ai_model": model,
    }


def _models() -> list[str]:
    result = []
    for model in MODEL_CHAIN:
        model = _as_text(model)
        if model and model not in result:
            result.append(model)
    return result


def generate_article(topic):
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        timeout=120,
        max_retries=0,
    )

    prompt = f'''Источник темы: {_as_text(topic.get('source', ''))}
Заголовок исходной темы: {_as_text(topic.get('title', ''))}
Ссылка: {_as_text(topic.get('link', ''))}
Описание: {_as_text(topic.get('summary', ''))}

Сделай самостоятельный материал {MIN_ARTICLE_WORDS}–{MAX_ARTICLE_WORDS} слов. Нужны лид, 5–8 подзаголовков, практические пункты и честный вывод.
Сразу предложи 5 разных заголовков, затем выбери смысловую категорию только из: Что купить; Стоит ли брать; Экономия; Сравнения; Авто-технологии.
Верни ТОЛЬКО JSON: headline, headlines (array из 5 строк), category, article_markdown, fact_check (array), image_prompt, source_urls (array), commercial_intent (0..10).'''

    errors = []
    for model in _models():
        try:
            if not reserve():
                raise RuntimeError(
                    f"Дневной лимит OpenRouter исчерпан ({OPENROUTER_DAILY_LIMIT} запросов)"
                )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.55,
            )
            raw = response.choices[0].message.content or ""
            data = _extract(raw)
            if not data:
                raise ValueError("AI вернул невалидный JSON")
            normalized = _normalize(data, model)
            log.info("Article generated with model %s", model)
            return normalized
        except Exception as exc:
            message = f"{model}: {exc}"
            errors.append(message)
            log.warning("AI generation failed: %s", message)
            # Avoid wasting scarce free-tier requests by retrying the same
            # failing model. Move immediately to the next free provider/model.
            if "429" in str(exc).lower():
                time.sleep(1)

    raise RuntimeError("Все AI-модели недоступны: " + " | ".join(errors[-5:]))
