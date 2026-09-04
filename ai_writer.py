import json
import logging
import re
from typing import Any

import requests
from openai import OpenAI

from config import (
    CHANNEL_NAME, DEEPSEEK_MODEL, MAX_ARTICLE_WORDS, MIN_ARTICLE_WORDS,
    OPENAI_API_KEY, OPENAI_MODEL, OPENROUTER_API_KEY, OPENROUTER_DAILY_LIMIT,
    OPENROUTER_EDITOR_MODEL, OPENROUTER_MODEL, YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_MODEL,
)
from quota import reserve
from quality_checker import check_article

log = logging.getLogger(__name__)
SYSTEM = f'''Ты главный редактор автомобильного канала «{CHANNEL_NAME}». Пиши оригинальные, конкретные и полезные материалы на русском языке.
Не копируй источники. Не выдумывай цены, характеристики, законы, статистику, цитаты и результаты тестов.
Не используй абсолютные формулировки вроде «всегда», «никогда», «100%», «гарантированно».
Если факт не подтверждается входным источником, не включай его как установленный факт.
Материал должен помогать читателю экономить деньги и избегать ошибок при покупке и владении автомобилем.'''


def _as_text(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, str): return value.strip()
    if isinstance(value, (dict, list)): return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _as_string_list(value: Any) -> list[str]:
    if value is None: return []
    if not isinstance(value, list): value = [value]
    return [text for item in value if (text := _as_text(item))]


def _extract(value: Any):
    if isinstance(value, dict): return value
    value = _as_text(value)
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S)
    try: return json.loads(value)
    except Exception:
        match = re.search(r"\{.*\}", value, re.S)
        if not match: return None
        try: return json.loads(match.group(0))
        except Exception: return None


def _normalize(data: Any, provider: str, model: str) -> dict:
    if not isinstance(data, dict): raise ValueError("AI вернул некорректную структуру")
    headline = _as_text(data.get("headline")); headlines = _as_string_list(data.get("headlines"))
    if headline and headline not in headlines: headlines.insert(0, headline)
    if not headline and headlines: headline = headlines[0]
    article = _as_text(data.get("article_markdown"))
    if not headline or not article: raise ValueError("AI не вернул обязательные поля статьи")
    category = _as_text(data.get("category"))
    if category not in {"Что купить", "Стоит ли брать", "Экономия", "Сравнения", "Авто-технологии"}: category = "Стоит ли брать"
    try: commercial = max(0, min(10, int(float(data.get("commercial_intent", 5)))))
    except (TypeError, ValueError): commercial = 5
    return {"headline": headline, "headlines": headlines[:5] or [headline], "category": category,
            "article_markdown": article, "fact_check": _as_string_list(data.get("fact_check")),
            "image_prompt": _as_text(data.get("image_prompt")), "source_urls": _as_string_list(data.get("source_urls")),
            "commercial_intent": commercial, "ai_provider": provider, "ai_model": model,
            "ai_stages": [f"{provider}:{model}"]}


def _merge_editor(original: dict, edited: dict, provider: str, model: str) -> dict:
    merged = dict(original)
    for key in ("headline", "headlines", "category", "article_markdown", "fact_check", "image_prompt", "source_urls", "commercial_intent"):
        value = edited.get(key)
        if value not in (None, "", []): merged[key] = value
    normalized = _normalize(merged, provider, model)
    normalized["ai_stages"] = original.get("ai_stages", []) + [f"{provider}:{model}"]
    return normalized


def _source_urls(topic: dict) -> list[str]:
    link = _as_text(topic.get("link"))
    return [link] if link.startswith(("http://", "https://")) else []


def _article_prompt(topic: dict) -> str:
    sources = _source_urls(topic)
    return f'''Источник темы: {_as_text(topic.get('source'))}
Заголовок исходной темы: {_as_text(topic.get('title'))}
Ссылка: {_as_text(topic.get('link'))}
Описание источника: {_as_text(topic.get('summary'))}

Напиши самостоятельный материал объёмом {MIN_ARTICLE_WORDS + 100}–{MAX_ARTICLE_WORDS - 100} слов, чтобы после редактуры гарантированно остаться в диапазоне {MIN_ARTICLE_WORDS}–{MAX_ARTICLE_WORDS}.
Структура: сильный короткий лид; 5–8 содержательных подзаголовков ##; практический чек-лист; блок рисков; честный вывод.
Запрещены слова «всегда», «никогда», «100%», «гарантированно», «самый лучший». Не выдумывай факты и цифры.
Не придумывай URL. source_urls должен содержать только реально переданные ссылки: {json.dumps(sources, ensure_ascii=False)}.
fact_check: 3–8 конкретных утверждений, реально присутствующих в статье и допускающих проверку по источнику.
image_prompt обязателен: реалистичная автомобильная редакционная обложка без логотипов и текста.
Предложи 5 разных заголовков. Категория только из: Что купить; Стоит ли брать; Экономия; Сравнения; Авто-технологии.
Верни ТОЛЬКО валидный JSON: headline, headlines, category, article_markdown, fact_check, image_prompt, source_urls, commercial_intent.'''


def _or_client():
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1", timeout=120, max_retries=1)


def _or_call(model: str, messages: list[dict], temperature: float = 0.25):
    if not reserve(): raise RuntimeError(f"Дневной лимит OpenRouter исчерпан ({OPENROUTER_DAILY_LIMIT})")
    return _or_client().chat.completions.create(model=model, messages=messages, temperature=temperature)


def _openrouter_draft(topic: dict) -> dict:
    if not OPENROUTER_API_KEY: raise RuntimeError("OPENROUTER_API_KEY не задан")
    models = []
    for model in (DEEPSEEK_MODEL, OPENROUTER_MODEL, "openrouter/free"):
        if model and model not in models: models.append(model)
    errors = []
    for model in models:
        try:
            response = _or_call(model, [{"role":"system","content":SYSTEM},{"role":"user","content":_article_prompt(topic)}], 0.35)
            provider = "DeepSeek/OpenRouter" if model == DEEPSEEK_MODEL else "OpenRouter"
            data = _normalize(_extract(response.choices[0].message.content or ""), provider, model)
            if not data["source_urls"]: data["source_urls"] = _source_urls(topic)
            return data
        except Exception as exc: errors.append(f"{model}: {exc}")
    raise RuntimeError("OpenRouter недоступен: " + " | ".join(errors))


def _editor_prompt(data: dict, editor_name: str, extra: str = "") -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f'''Ты {editor_name} автомобильного медиа. Проведи строгую редактуру.
Финальный текст обязан иметь {MIN_ARTICLE_WORDS}–{MAX_ARTICLE_WORDS} слов, 5–8 подзаголовков ##, практический чек-лист, риски и вывод.
Удали абсолютные утверждения и неподтверждённые цифры. Не выдумывай URL. Сохрани реальный source_urls, fact_check и image_prompt.
Перед ответом мысленно проверь объём и все требования. {extra}
Верни ТОЛЬКО JSON с полями headline, headlines, category, article_markdown, fact_check, image_prompt, source_urls, commercial_intent.
Материал: {payload}'''


def _yandex_edit(data: dict) -> dict:
    if not (YANDEX_API_KEY and YANDEX_FOLDER_ID):
        raise RuntimeError("Yandex AI не настроен: нужны YANDEX_API_KEY и YANDEX_FOLDER_ID")
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    body = {"modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}", "completionOptions":{"stream":False,"temperature":0.15,"maxTokens":8000},
            "messages":[{"role":"system","text":SYSTEM},{"role":"user","text":_editor_prompt(data,"обязательный редактор YandexGPT")} ]}
    response = requests.post(url, headers={"Authorization":f"Api-Key {YANDEX_API_KEY}","Content-Type":"application/json"}, json=body, timeout=120)
    response.raise_for_status()
    parsed = _extract(response.json()["result"]["alternatives"][0]["message"]["text"])
    if not isinstance(parsed, dict): raise ValueError("Yandex AI вернул некорректный JSON")
    return _merge_editor(data, parsed, "YandexGPT", YANDEX_MODEL)


def _openai_edit(data: dict, extra: str = "") -> dict:
    prompt = _editor_prompt(data, "финальный редактор OpenAI", extra)
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY, timeout=120, max_retries=1)
        response = client.chat.completions.create(model=OPENAI_MODEL, messages=[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}])
        parsed = _extract(response.choices[0].message.content or "")
        if not isinstance(parsed, dict): raise ValueError("OpenAI вернул некорректный JSON")
        return _merge_editor(data, parsed, "OpenAI", OPENAI_MODEL)
    if not OPENROUTER_API_KEY: raise RuntimeError("Нет OpenAI/OpenRouter редактора")
    errors = []
    for model in (OPENROUTER_EDITOR_MODEL, "openrouter/free"):
        try:
            response = _or_call(model, [{"role":"system","content":SYSTEM},{"role":"user","content":prompt}], 0.1)
            parsed = _extract(response.choices[0].message.content or "")
            if not isinstance(parsed, dict): raise ValueError("некорректный JSON")
            return _merge_editor(data, parsed, "OpenAI/OpenRouter", model)
        except Exception as exc: errors.append(f"{model}: {exc}")
    raise RuntimeError("OpenAI/OpenRouter editor недоступен: " + " | ".join(errors))


def _repair(data: dict, topic: dict) -> dict:
    for attempt in range(2):
        quality = check_article(data)
        if quality["ok"]: return data
        details = "; ".join(quality["problems"])
        extra = f'''Это ремонт качества, попытка {attempt + 1}. Исправь КАЖДУЮ проблему: {details}.
Не меняй реальную ссылку источника. Цель — итоговая проверка без единой критической проблемы и score >= 90.'''
        data = _openai_edit(data, extra)
        if not data.get("source_urls"): data["source_urls"] = _source_urls(topic)
    return data


def generate_article(topic):
    if not _source_urls(topic):
        raise ValueError("Тема без реального URL источника не допускается в production")
    data = _openrouter_draft(topic)
    # YandexGPT is mandatory for production, per editorial architecture.
    data = _yandex_edit(data)
    data = _openai_edit(data)
    if not data.get("source_urls"): data["source_urls"] = _source_urls(topic)
    data = _repair(data, topic)
    final_quality = check_article(data)
    if not final_quality["ok"]:
        raise ValueError("Материал не прошёл финальный quality gate: " + "; ".join(final_quality["problems"]))
    return data
