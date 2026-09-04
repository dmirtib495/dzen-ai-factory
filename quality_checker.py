import json
import re
from typing import Any

from config import MIN_ARTICLE_WORDS, MAX_ARTICLE_WORDS


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [text for item in value if (text := _text(item))]


def check_article(data):
    problems = []
    warnings = []

    if not isinstance(data, dict):
        return {
            "ok": False,
            "problems": ["Некорректный формат материала"],
            "warnings": [],
            "words": 0,
            "score": 0,
        }

    text = _text(data.get("article_markdown"))
    headline = _text(data.get("headline"))
    fact_check = _items(data.get("fact_check"))
    sources = _items(data.get("source_urls"))
    image_prompt = _text(data.get("image_prompt"))

    words = len(re.findall(r"\b\w+\b", text, flags=re.U))
    headings = len(re.findall(r"^#{2,3}\s+", text, re.M))

    if words < MIN_ARTICLE_WORDS:
        problems.append(f"Мало слов: {words}")
    if words > MAX_ARTICLE_WORDS + 250:
        problems.append(f"Слишком много слов: {words}")
    if len(headline) < 25:
        problems.append("Слабый/короткий заголовок")
    if len(headline) > 140:
        warnings.append("Слишком длинный заголовок")
    if not fact_check:
        problems.append("Нет списка проверки фактов")
    if not image_prompt:
        problems.append("Нет промпта изображения")
    if headings < 4:
        problems.append("Мало подзаголовков")

    if re.search(r"\b(100%|гарантированно|точно лучший|самый лучший|никогда|всегда)\b", text, re.I):
        problems.append("Есть абсолютные утверждения")

    suspicious = [
        r"\bкак известно\b",
        r"\bэксперты утверждают\b",
        r"\bисследования показывают\b",
        r"\bпо статистике\b",
        r"\bпо данным исследований\b",
    ]
    if any(re.search(pattern, text, re.I) for pattern in suspicious) and not sources:
        problems.append("Есть ссылки на данные/экспертов без источников")

    if "нужно проверить" in text.lower():
        warnings.append("В тексте остались факты с пометкой «нужно проверить»")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    normalized = [re.sub(r"\W+", " ", p.lower()).strip() for p in paragraphs]
    if len(normalized) != len(set(normalized)):
        warnings.append("Обнаружены повторяющиеся абзацы")

    score = 100
    score -= 18 * len(problems)
    score -= 6 * len(warnings)
    score = max(0, min(100, score))

    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "words": words,
        "score": score,
    }
