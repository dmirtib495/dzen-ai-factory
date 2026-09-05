import json
import logging
import re
from typing import Any

import requests
from openai import OpenAI

from config import (
    DEEPSEEK_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_EDITOR_MODEL,
    OPENROUTER_MODEL,
    YANDEX_API_KEY,
    YANDEX_FOLDER_ID,
    YANDEX_MODEL,
)
from editorial_prompts import (
    EDITORIAL_SYSTEM,
    draft_prompt,
    final_editor_prompt,
    quality_auditor_prompt,
    repair_prompt,
    yandex_editor_prompt,
)
from quality_checker import check_article
from quota import record_success

log = logging.getLogger(__name__)


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


def _source_evidence(topic: dict) -> dict:
    return {
        "title": _as_text(topic.get("title")),
        "source": _as_text(topic.get("source")),
        "url": _as_text(topic.get("link")),
        "summary": _as_text(topic.get("summary")),
    }


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

    allowed_categories = {"Что купить", "Стоит ли брать", "Экономия", "Сравнения", "Авто-технологии"}
    category = _as_text(data.get("category"))
    if category not in allowed_categories:
        category = "Стоит ли брать"
    try:
        commercial = max(0, min(10, int(float(data.get("commercial_intent", 5)))))
    except (TypeError, ValueError):
        commercial = 5

    result = {
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
    if isinstance(data.get("ai_quality_audit"), dict):
        result["ai_quality_audit"] = data["ai_quality_audit"]
    if isinstance(data.get("source_evidence"), dict):
        result["source_evidence"] = dict(data["source_evidence"])
    return result


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
    if "ai_quality_audit" in original:
        normalized["ai_quality_audit"] = original["ai_quality_audit"]
    return normalized


def _source_urls(topic: dict) -> list[str]:
    link = _as_text(topic.get("link"))
    return [link] if link.startswith(("http://", "https://")) else []


def _or_client():
    # Outer retry logic below knows the difference between malformed JSON and
    # a hard daily free-tier limit. SDK retries only multiplied 429 requests.
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1", timeout=120, max_retries=0)


def _or_call(model: str, messages: list[dict], temperature: float = 0.2):
    response = _or_client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
        extra_body={"provider": {"require_parameters": True}},
    )
    try:
        record_success()
    except Exception:
        log.exception("OpenRouter usage telemetry failed after successful request")
    return response


def _actual_model(response, requested_model: str) -> str:
    return _as_text(getattr(response, "model", "")) or requested_model


def _is_openrouter_free_daily_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "free-models-per-day" in text
        or "openrouter_free_tier_daily" in text
        or ("rate limit exceeded" in text and "free" in text and "daily" in text)
    )


def _openrouter_json(models: list[str], prompt: str, role: str, temperature: float, provider_name: str):
    errors = []
    unique_models = list(dict.fromkeys(m for m in models if m))
    for requested_model in unique_models:
        for attempt in (1, 2):
            try:
                retry_note = "" if attempt == 1 else (
                    "\n\nПОВТОР ПОСЛЕ ОШИБКИ ФОРМАТА: верни только один JSON-объект "
                    "без markdown, пояснений до/после JSON и без незакрытых строк."
                )
                response = _or_call(
                    requested_model,
                    [
                        {"role": "system", "content": EDITORIAL_SYSTEM},
                        {"role": "user", "content": prompt + retry_note},
                    ],
                    temperature,
                )
                actual_model = _actual_model(response, requested_model)
                parsed = _extract(response.choices[0].message.content or "")
                if not isinstance(parsed, dict):
                    raise ValueError("модель вернула не JSON")
                log.info(
                    "OpenRouter JSON OK role=%s requested=%s actual=%s attempt=%s",
                    role, requested_model, actual_model, attempt,
                )
                return parsed, requested_model, actual_model
            except Exception as exc:
                errors.append(f"{requested_model} attempt {attempt}: {exc}")
                log.warning(
                    "OpenRouter JSON failure role=%s requested=%s attempt=%s error=%s",
                    role, requested_model, attempt, exc,
                )
                if _is_openrouter_free_daily_limit(exc):
                    log.warning(
                        "OpenRouter hard daily free-tier limit for requested=%s; skipping retries and moving to fallback",
                        requested_model,
                    )
                    break
    raise RuntimeError(f"{role} недоступен: " + " | ".join(errors))


def _draft(topic: dict) -> dict:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")
    sources = _source_urls(topic)
    parsed, requested_model, actual_model = _openrouter_json(
        [DEEPSEEK_MODEL, OPENROUTER_MODEL, "openrouter/free"],
        draft_prompt(topic, sources),
        "Автор-аналитик",
        0.32,
        "DeepSeek/OpenRouter",
    )
    provider = "FixedFree/OpenRouter" if requested_model == DEEPSEEK_MODEL else "OpenRouter"
    data = _normalize(parsed, provider, actual_model)
    data["source_urls"] = sources
    data["source_evidence"] = _source_evidence(topic)
    log.info(
        "DRAFT_OK headline=%r model=%s source_summary_chars=%s",
        data.get("headline"), actual_model, len(data["source_evidence"].get("summary", "")),
    )
    return data


def _yandex_edit(data: dict) -> dict:
    if not (YANDEX_API_KEY and YANDEX_FOLDER_ID):
        raise RuntimeError("Yandex AI не настроен: нужны YANDEX_API_KEY и YANDEX_FOLDER_ID")
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    body = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
        "completionOptions": {"stream": False, "temperature": 0.12, "maxTokens": 9000},
        "messages": [
            {"role": "system", "text": EDITORIAL_SYSTEM},
            {"role": "user", "text": yandex_editor_prompt(data)},
        ],
    }
    response = requests.post(
        url,
        headers={"Authorization": f"Api-Key {YANDEX_API_KEY}", "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    response.raise_for_status()
    parsed = _extract(response.json()["result"]["alternatives"][0]["message"]["text"])
    if not isinstance(parsed, dict):
        raise ValueError("YandexGPT вернул некорректный JSON")
    log.info("YandexGPT edit OK model=%s", YANDEX_MODEL)
    return _merge_editor(data, parsed, "YandexGPT", YANDEX_MODEL)


def _final_edit(data: dict, repair_notes: str = "") -> dict:
    prompt = final_editor_prompt(data, repair_notes)
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY, timeout=120, max_retries=1)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": EDITORIAL_SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.08,
        )
        parsed = _extract(response.choices[0].message.content or "")
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI вернул некорректный JSON")
        return _merge_editor(data, parsed, "OpenAI", OPENAI_MODEL)

    parsed, requested_model, actual_model = _openrouter_json(
        [OPENROUTER_EDITOR_MODEL, "openrouter/free"],
        prompt,
        "Финальный редактор",
        0.08,
        "OpenAI/OpenRouter",
    )
    return _merge_editor(data, parsed, "OpenAI/OpenRouter", actual_model)


def _quality_audit(data: dict) -> dict:
    parsed, requested_model, actual_model = _openrouter_json(
        [OPENROUTER_EDITOR_MODEL, OPENROUTER_MODEL, "openrouter/free"],
        quality_auditor_prompt(data),
        "Независимый quality auditor",
        0.0,
        "QualityAudit/OpenRouter",
    )
    verdict = _as_text(parsed.get("verdict")).upper()
    try:
        total_score = int(float(parsed.get("total_score", 0)))
    except (TypeError, ValueError):
        total_score = 0
    audit = {
        "verdict": verdict if verdict in {"PASS", "REVISE", "REJECT"} else "REVISE",
        "total_score": max(0, min(100, total_score)),
        "scores": parsed.get("scores") if isinstance(parsed.get("scores"), dict) else {},
        "blocking_issues": _as_string_list(parsed.get("blocking_issues")),
        "improvements": _as_string_list(parsed.get("improvements")),
        "fact_risks": _as_string_list(parsed.get("fact_risks")),
        "strengths": _as_string_list(parsed.get("strengths")),
        "auditor_model": actual_model,
    }
    data["ai_quality_audit"] = audit
    data["ai_stages"] = data.get("ai_stages", []) + [f"QualityAudit/OpenRouter:{actual_model}"]
    return audit


def _mechanical_quality_cleanup(data: dict) -> dict:
    """Fix only deterministic presentation defects without inventing facts."""
    text = _as_text(data.get("article_markdown"))
    headline = _as_text(data.get("headline"))

    replacements = [
        (r"\b100\s*%\b", "без абсолютной гарантии"),
        (r"\bгарантированно\b", "с оговорками"),
        (r"\bточно лучший\b", "может оказаться подходящим"),
        (r"\bсамый лучший\b", "один из подходящих вариантов"),
        (r"\bникогда\b", "как правило, не"),
        (r"\bвсегда\b", "обычно"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
        headline = re.sub(pattern, replacement, headline, flags=re.I)

    heading_seen = 0
    lines = []
    for line in text.splitlines():
        if re.match(r"^##\s+", line):
            heading_seen += 1
            if heading_seen > 8:
                line = "**" + re.sub(r"^##\s+", "", line).strip() + "**"
        lines.append(line)
    data["article_markdown"] = "\n".join(lines).strip()
    data["headline"] = headline.strip()
    return data


def _repair(data: dict, topic: dict) -> dict:
    for attempt in range(1, 4):
        data = _mechanical_quality_cleanup(data)
        deterministic = check_article(data, require_ai_audit=False)
        audit = _quality_audit(data)
        log.info(
            "REPAIR_CHECK attempt=%s deterministic_ok=%s score=%s words=%s headings=%s problems=%s audit_verdict=%s audit_score=%s blocking=%s",
            attempt,
            deterministic.get("ok"),
            deterministic.get("score"),
            deterministic.get("words"),
            deterministic.get("headings"),
            deterministic.get("problems"),
            audit.get("verdict"),
            audit.get("total_score"),
            audit.get("blocking_issues"),
        )
        if deterministic["ok"] and audit["verdict"] == "PASS" and audit["total_score"] >= 90 and not audit["blocking_issues"]:
            return data

        parsed, requested_model, actual_model = _openrouter_json(
            [OPENROUTER_EDITOR_MODEL, OPENROUTER_MODEL, "openrouter/free"],
            repair_prompt(data, deterministic["problems"], audit, attempt),
            "Senior rewrite editor",
            0.08,
            "Repair/OpenRouter",
        )
        data = _merge_editor(data, parsed, "Repair/OpenRouter", actual_model)
        data["source_urls"] = _source_urls(topic)
        data["source_evidence"] = _source_evidence(topic)
        data.pop("ai_quality_audit", None)

    data = _mechanical_quality_cleanup(data)
    _quality_audit(data)
    return data


def generate_article(topic):
    sources = _source_urls(topic)
    if not sources:
        raise ValueError("Тема без реального URL источника не допускается в production")

    data = _draft(topic)
    data = _yandex_edit(data)
    data["source_urls"] = sources
    data["source_evidence"] = _source_evidence(topic)
    data = _final_edit(data)
    data["source_urls"] = sources
    data["source_evidence"] = _source_evidence(topic)
    data = _repair(data, topic)
    data["source_urls"] = sources
    data["source_evidence"] = _source_evidence(topic)
    data = _mechanical_quality_cleanup(data)

    final_quality = check_article(data, require_ai_audit=True)
    if not final_quality["ok"]:
        details = list(final_quality.get("problems") or [])
        if not details:
            details = [
                f"Итоговый score ниже 90: {final_quality.get('score')}",
                *(final_quality.get("warnings") or []),
            ]
        raise ValueError("Материал не прошёл финальный professional quality gate: " + "; ".join(details))
    data.pop("source_evidence", None)
    return data


# Compatibility aliases used by CI/tests.
BASE_SYSTEM = EDITORIAL_SYSTEM
_article_prompt = lambda topic: draft_prompt(topic, _source_urls(topic))
_yandex_prompt = yandex_editor_prompt
_final_prompt = final_editor_prompt
