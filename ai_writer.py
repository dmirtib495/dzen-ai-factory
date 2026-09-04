import json
import logging
import re
from typing import Any

import requests
from openai import OpenAI

from config import (
    CHANNEL_NAME,
    DEEPSEEK_MODEL,
    MAX_ARTICLE_WORDS,
    MIN_ARTICLE_WORDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_DAILY_LIMIT,
    OPENROUTER_EDITOR_MODEL,
    OPENROUTER_MODEL,
    YANDEX_API_KEY,
    YANDEX_FOLDER_ID,
    YANDEX_MODEL,
)
from quota import reserve
from quality_checker import check_article

log = logging.getLogger(__name__)

BASE_SYSTEM = f'''Ты работаешь в редакции автомобильного канала «{CHANNEL_NAME}».
Цель канала: помогать обычному автовладельцу или покупателю принимать более выгодные решения, избегать лишних расходов и понимать риски без жаргона и рекламной воды.

Редакционные правила:
1. Пиши по-русски естественно, живо и профессионально. Текст должен звучать как сильный человеческий автомобильный редактор, а не как шаблон ИИ.
2. Не копируй формулировки источника и не пересказывай новость абзац за абзацем. Создавай самостоятельный полезный материал вокруг подтверждённой темы.
3. Не выдумывай факты, характеристики, цены, пробеги, проценты, статистику, исследования, законы, цитаты, результаты тестов или мнения экспертов.
4. Если входные данные не подтверждают конкретную цифру или факт, либо убери его, либо сформулируй как общий практический принцип без фиктивной конкретики.
5. Не используй в тексте слова и конструкции, которые создают ложную абсолютность: «всегда», «никогда», «100%», «гарантированно», «самый лучший», «точно лучший».
6. Не пиши канцеляритом и общими фразами вроде «автомобиль играет важную роль в жизни современного человека».
7. Каждый раздел должен отвечать на практический вопрос читателя: что смотреть, почему это важно, какой риск, что спросить, как проверить или где можно переплатить.
8. Не используй агрессивный кликбейт, запугивание, обещания гарантированной экономии и рекламные призывы.
9. Не придумывай URL. Разрешены только ссылки, реально переданные во входных данных.
10. Финальный материал должен быть пригоден к публикации без ручной литературной доработки.'''

DRAFT_ROLE = '''Твоя роль на этом этапе — автор-аналитик. Сначала мысленно отдели подтверждённые входные факты от того, чего во входе нет. Затем построй полезную статью так, чтобы она не зависела от выдуманных подробностей.'''

YANDEX_ROLE = '''Твоя роль — русскоязычный выпускающий редактор YandexGPT. Улучши естественность русского языка, связность, практическую ценность и читабельность. Удали машинный стиль, повторы, штампы и пустые абзацы. Не сокращай материал ниже целевого объёма и не добавляй неподтверждённые факты.'''

FINAL_ROLE = '''Твоя роль — финальный редактор и контролёр качества. Отнесись к черновику критически: найди рискованные утверждения, логические провалы, повторы, искусственные формулировки и места без практической пользы. Перепиши проблемные места, но сохрани фактическую осторожность и реальный источник.'''


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
    allowed_categories = {"Что купить", "Стоит ли брать", "Экономия", "Сравнения", "Авто-технологии"}
    if category not in allowed_categories:
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


def _merge_editor(original: dict, edited: dict, provider: str, model: str) -> dict:
    merged = dict(original)
    for key in (
        "headline", "headlines", "category", "article_markdown", "fact_check",
        "image_prompt", "source_urls", "commercial_intent",
    ):
        value = edited.get(key)
        if value not in (None, "", []):
            merged[key] = value
    normalized = _normalize(merged, provider, model)
    normalized["ai_stages"] = original.get("ai_stages", []) + [f"{provider}:{model}"]
    return normalized


def _source_urls(topic: dict) -> list[str]:
    link = _as_text(topic.get("link"))
    return [link] if link.startswith(("http://", "https://")) else []


def _article_prompt(topic: dict) -> str:
    sources = _source_urls(topic)
    target_min = max(MIN_ARTICLE_WORDS + 150, 1050)
    target_max = min(MAX_ARTICLE_WORDS - 100, 1300)
    return f'''{DRAFT_ROLE}

ВХОДНЫЕ ДАННЫЕ
Источник: {_as_text(topic.get('source'))}
Тема источника: {_as_text(topic.get('title'))}
URL источника: {_as_text(topic.get('link'))}
Краткое описание/RSS-аннотация: {_as_text(topic.get('summary'))}
Разрешённые URL: {json.dumps(sources, ensure_ascii=False)}

ЗАДАЧА
Создай самостоятельную статью для «{CHANNEL_NAME}».
Целевой объём именно поля article_markdown: {target_min}–{target_max} русских слов. Не считай JSON, заголовки списка headlines и служебные поля частью объёма.

ТРЕБУЕМАЯ КОМПОЗИЦИЯ article_markdown
- лид 2–3 абзаца: конкретная проблема читателя и зачем дочитать;
- 5–8 осмысленных разделов с Markdown-подзаголовками ##;
- в основных разделах объясняй причинно-следственную связь, а не перечисляй банальности;
- отдельный раздел с практическим чек-листом действий;
- отдельный раздел «Где можно ошибиться или переплатить» либо близкий по смыслу;
- финальный вывод: кому совет полезен и какое решение принять следующим шагом.

СТИЛЬ
- абзацы преимущественно по 2–5 предложений;
- допускаются маркированные списки, но статья не должна превращаться в один длинный список;
- не начинай разделы одинаковыми шаблонами;
- не используй фразы «в данной статье», «следует отметить», «важно понимать», если без них смысл не теряется;
- не повторяй заголовок статьи в первом предложении;
- обращение к читателю допустимо, но без фамильярности;
- не упоминай, что текст создан ИИ или проходит редактуру.

ФАКТЫ И ИСТОЧНИКИ
Используй конкретные факты только тогда, когда они прямо следуют из переданных заголовка/аннотации. У тебя нет права притворяться, будто ты открыл URL и прочитал полный материал.
Если входных фактов мало, строь статью на универсальных проверочных действиях и логике владения автомобилем, а не на придуманных цифрах.
source_urls должен в точности содержать только разрешённые URL.
fact_check должен содержать 3–6 коротких редакционных пунктов. Каждый пункт формулируй так: «Проверить: <конкретное утверждение из статьи>». Не добавляй в статью сомнительный факт только ради заполнения fact_check.

ЗАГОЛОВКИ
Сгенерируй ровно 5 разных headlines длиной примерно 45–90 знаков. Они должны обещать конкретную пользу, но не обещать невозможного. Используй разные конструкции: вопрос, практическая формулировка, ошибка/риск, сравнение или экономический угол. Не ставь два и более восклицательных знака.
headline — лучший из этих пяти.

IMAGE_PROMPT
image_prompt: 1–2 предложения на английском для реалистичной редакционной автомобильной фотографии 16:9. Укажи сцену, тип автомобиля/деталь, естественный свет и реалистичную среду. Без текста, логотипов, водяных знаков, брендинга и фантастических элементов.

ВЫХОД
Верни только один валидный JSON-объект без Markdown-обёртки и комментариев. Ровно эти поля:
headline, headlines, category, article_markdown, fact_check, image_prompt, source_urls, commercial_intent.
category — только одно из: Что купить; Стоит ли брать; Экономия; Сравнения; Авто-технологии.
commercial_intent — целое число 0–10.'''


def _or_client():
    return OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        timeout=120,
        max_retries=1,
    )


def _or_call(model: str, messages: list[dict], temperature: float = 0.25):
    if not reserve():
        raise RuntimeError(f"Дневной лимит OpenRouter исчерпан ({OPENROUTER_DAILY_LIMIT})")
    return _or_client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )


def _openrouter_draft(topic: dict) -> dict:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")
    models = []
    for model in (DEEPSEEK_MODEL, OPENROUTER_MODEL, "openrouter/free"):
        if model and model not in models:
            models.append(model)
    errors = []
    for model in models:
        try:
            response = _or_call(
                model,
                [
                    {"role": "system", "content": BASE_SYSTEM},
                    {"role": "user", "content": _article_prompt(topic)},
                ],
                0.32,
            )
            provider = "DeepSeek/OpenRouter" if model == DEEPSEEK_MODEL else "OpenRouter"
            data = _normalize(_extract(response.choices[0].message.content or ""), provider, model)
            if not data["source_urls"]:
                data["source_urls"] = _source_urls(topic)
            return data
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("OpenRouter недоступен: " + " | ".join(errors))


def _yandex_prompt(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f'''{YANDEX_ROLE}

Отредактируй материал ниже как выпускающий редактор русскоязычного автомобильного медиа.

ЖЁСТКИЕ УСЛОВИЯ
- article_markdown после твоей правки: 1000–1300 слов и в любом случае не меньше {MIN_ARTICLE_WORDS} и не больше {MAX_ARTICLE_WORDS};
- 5–8 подзаголовков уровня ##;
- сохранить практический чек-лист, блок рисков/переплаты и содержательный вывод;
- сохранить только реальные source_urls из входа, не добавлять новые URL;
- не добавлять новые числа, факты, характеристики, нормы закона или статистику, которых нет во входном материале;
- удалить повторы, штампы, канцелярит и машинные переходы;
- не употреблять запрещённые абсолютные слова из системных правил даже в отрицательных конструкциях;
- сделать текст естественным для русскоязычного читателя: разная длина предложений, понятные формулировки, конкретные действия;
- headlines: оставить ровно 5 сильных, различающихся заголовков; headline должен совпадать с одним из них;
- fact_check: 3–6 пунктов формата «Проверить: ...», относящихся к реальным утверждениям статьи;
- image_prompt сохранить или улучшить, но он должен остаться на английском, 16:9, realistic editorial automotive photo, без текста и логотипов.

Не объясняй правки. Верни только валидный JSON с полями:
headline, headlines, category, article_markdown, fact_check, image_prompt, source_urls, commercial_intent.

МАТЕРИАЛ
{payload}'''


def _final_prompt(data: dict, extra: str = "") -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f'''{FINAL_ROLE}

ФИНАЛЬНАЯ ПРОВЕРКА ПЕРЕД ПУБЛИКАЦИЕЙ
Перепиши материал только там, где это улучшает качество, но верни полностью готовую финальную версию.

Критерии допуска:
1. article_markdown — 1000–1300 слов, допустимый технический коридор {MIN_ARTICLE_WORDS}–{MAX_ARTICLE_WORDS}.
2. Минимум 5 и максимум 8 подзаголовков ##.
3. Нет повторяющихся абзацев, пустых вступлений и SEO-воды.
4. Есть практический чек-лист, риски/переплата и конкретный вывод.
5. Ни одного неподтверждённого числа, статистики, закона, цитаты или «мнения экспертов».
6. Ни одного нового URL; source_urls сохранить из входа.
7. Не употреблять слова: «всегда», «никогда», «100%», «гарантированно», «самый лучший», «точно лучший».
8. Заголовок полезный и конкретный, без дешёвого кликбейта; headlines — ровно 5 вариантов.
9. fact_check — 3–6 конкретных пунктов «Проверить: ...».
10. Текст должен ощущаться как законченная статья редакции, а не инструкция для автора и не отчёт о проверке.
11. Не пиши внутри article_markdown ссылки на source_urls и не упоминай служебные поля.
12. Сохрани категорию из разрешённого списка и image_prompt.

{extra}

Перед выдачей мысленно проверь все 12 критериев. Не сообщай результат проверки и не добавляй пояснений.
Верни только валидный JSON с полями:
headline, headlines, category, article_markdown, fact_check, image_prompt, source_urls, commercial_intent.

МАТЕРИАЛ
{payload}'''


def _yandex_edit(data: dict) -> dict:
    if not (YANDEX_API_KEY and YANDEX_FOLDER_ID):
        raise RuntimeError("Yandex AI не настроен: нужны YANDEX_API_KEY и YANDEX_FOLDER_ID")
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    body = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
        "completionOptions": {"stream": False, "temperature": 0.15, "maxTokens": 8000},
        "messages": [
            {"role": "system", "text": BASE_SYSTEM},
            {"role": "user", "text": _yandex_prompt(data)},
        ],
    }
    response = requests.post(
        url,
        headers={
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=120,
    )
    response.raise_for_status()
    parsed = _extract(response.json()["result"]["alternatives"][0]["message"]["text"])
    if not isinstance(parsed, dict):
        raise ValueError("Yandex AI вернул некорректный JSON")
    return _merge_editor(data, parsed, "YandexGPT", YANDEX_MODEL)


def _openai_edit(data: dict, extra: str = "") -> dict:
    prompt = _final_prompt(data, extra)
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY, timeout=120, max_retries=1)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": BASE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        parsed = _extract(response.choices[0].message.content or "")
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI вернул некорректный JSON")
        return _merge_editor(data, parsed, "OpenAI", OPENAI_MODEL)

    if not OPENROUTER_API_KEY:
        raise RuntimeError("Нет OpenAI/OpenRouter редактора")
    errors = []
    for model in (OPENROUTER_EDITOR_MODEL, "openrouter/free"):
        try:
            response = _or_call(
                model,
                [
                    {"role": "system", "content": BASE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                0.08,
            )
            parsed = _extract(response.choices[0].message.content or "")
            if not isinstance(parsed, dict):
                raise ValueError("некорректный JSON")
            return _merge_editor(data, parsed, "OpenAI/OpenRouter", model)
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("OpenAI/OpenRouter editor недоступен: " + " | ".join(errors))


def _repair(data: dict, topic: dict) -> dict:
    for attempt in range(2):
        quality = check_article(data)
        if quality["ok"]:
            return data
        details = "; ".join(quality["problems"])
        extra = f'''РЕЖИМ ТОЧЕЧНОГО РЕМОНТА, попытка {attempt + 1}.
Автоматический валидатор нашёл: {details}.
Исправь каждую указанную проблему, не ухудшая уже выполненные требования.
Если проблема в объёме — доведи article_markdown примерно до 1150–1250 слов полезным содержанием, а не повторами.
Если найдена абсолютная формулировка — перепиши предложение целиком без запрещённого слова.
Если не хватает подзаголовков — логично раздели материал, не создавая пустых секций.
Если проблема в fact_check — добавляй только проверки реально присутствующих утверждений.
Реальный URL источника менять или дополнять запрещено.'''
        data = _openai_edit(data, extra)
        if not data.get("source_urls"):
            data["source_urls"] = _source_urls(topic)
    return data


def generate_article(topic):
    if not _source_urls(topic):
        raise ValueError("Тема без реального URL источника не допускается в production")
    data = _openrouter_draft(topic)
    data = _yandex_edit(data)
    data = _openai_edit(data)
    if not data.get("source_urls"):
        data["source_urls"] = _source_urls(topic)
    data = _repair(data, topic)
    final_quality = check_article(data)
    if not final_quality["ok"]:
        raise ValueError(
            "Материал не прошёл финальный quality gate: " + "; ".join(final_quality["problems"])
        )
    return data
