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


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wЁёА-Яа-я-]+\b", text, flags=re.U))


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip() and not p.lstrip().startswith("#")]


def check_article(data, require_ai_audit=True):
    problems = []
    warnings = []
    deductions = 0

    if not isinstance(data, dict):
        return {"ok": False, "problems": ["Некорректный формат материала"], "warnings": [], "words": 0, "score": 0}

    text = _text(data.get("article_markdown"))
    headline = _text(data.get("headline"))
    fact_check = _items(data.get("fact_check"))
    sources = _items(data.get("source_urls"))
    image_prompt = _text(data.get("image_prompt"))
    audit = data.get("ai_quality_audit") if isinstance(data.get("ai_quality_audit"), dict) else None

    words = _word_count(text)
    headings = re.findall(r"^##\s+(.+)$", text, re.M)
    paragraphs = _paragraphs(text)

    def critical(message: str, points: int = 15):
        nonlocal deductions
        problems.append(message)
        deductions += points

    def warn(message: str, points: int = 4):
        nonlocal deductions
        warnings.append(message)
        deductions += points

    if words < MIN_ARTICLE_WORDS:
        critical(f"Мало слов: {words}", 20)
    elif words < 1000:
        warn(f"Объём формально допустим, но ниже редакционного целевого: {words}", 5)
    if words > MAX_ARTICLE_WORDS:
        critical(f"Слишком много слов: {words}", 15)
    elif words > 1350:
        warn(f"Объём близок к верхней границе: {words}", 3)

    if not (35 <= len(headline) <= 110):
        critical("Заголовок вне профессионального диапазона длины", 10)
    if re.search(r"[!]{2,}|\?{2,}|\b(шок|сенсац|секрет,? который|вы не поверите)\b", headline, re.I):
        critical("Заголовок содержит дешёвый кликбейт", 15)
    if re.search(r"\b(100\s*%|гарантированно|точно лучший|самый лучший|никогда|всегда)\b", headline, re.I):
        critical("Заголовок содержит абсолютное обещание", 15)

    if not (5 <= len(headings) <= 8):
        critical(f"Нужно 5–8 содержательных подзаголовков, сейчас: {len(headings)}", 15)
    normalized_headings = [re.sub(r"\W+", " ", h.lower()).strip() for h in headings]
    if len(normalized_headings) != len(set(normalized_headings)):
        critical("Есть повторяющиеся подзаголовки", 10)

    checklist_present = bool(re.search(r"чек[- ]?лист|что проверить|порядок проверки|проверьте по пунктам", text, re.I))
    if not checklist_present:
        critical("Нет отдельного практического чек-листа", 15)

    risk_block_present = bool(re.search(r"ошиб|переплат|риск|где можно потерять|на чём теряют", text, re.I))
    if not risk_block_present:
        critical("Нет явного блока ошибок/рисков/переплаты", 12)

    if len(fact_check) < 3:
        critical("Недостаточно пунктов fact-check", 15)
    if any(not item.lower().startswith("проверить:") for item in fact_check):
        warn("Не все пункты fact-check имеют единый профессиональный формат «Проверить: ...»", 3)
    if not sources:
        critical("Нет реального первоисточника", 20)
    if any(not url.startswith(("http://", "https://")) for url in sources):
        critical("source_urls содержит некорректную ссылку", 15)
    if not image_prompt or len(image_prompt) < 35:
        critical("Нет полноценного image_prompt", 10)

    forbidden = r"\b(100\s*%|гарантированно|точно лучший|самый лучший|никогда|всегда)\b"
    if re.search(forbidden, text, re.I):
        critical("Есть абсолютные утверждения", 18)

    ai_cliches = [
        r"\bв данной статье\b", r"\bв современном мире\b", r"\bни для кого не секрет\b",
        r"\bследует отметить\b", r"\bважно понимать\b", r"\bподводя итог\b",
        r"\bкак искусственный интеллект\b", r"\bя не могу\b",
    ]
    hits = sum(len(re.findall(pattern, text, re.I)) for pattern in ai_cliches)
    if hits >= 2:
        critical(f"Выраженный шаблонный/ИИ-стиль: найдено {hits} клише", 12)
    elif hits == 1:
        warn("Есть единичное редакционное клише", 3)

    suspicious = [
        r"\bэксперты утверждают\b", r"\bисследования показывают\b", r"\bпо статистике\b",
        r"\bпо данным исследований\b", r"\bспециалисты доказали\b",
    ]
    if any(re.search(pattern, text, re.I) for pattern in suspicious):
        critical("Есть обобщённая ссылка на экспертов/исследования без конкретной доказательной опоры", 18)

    if re.search(r"\bнужно проверить\b|\bтребует проверки\b|\bуточнить источник\b", text, re.I):
        critical("В опубликованном тексте остались редакционные пометки о непроверенных фактах", 18)

    normalized_paragraphs = [re.sub(r"\W+", " ", p.lower()).strip() for p in paragraphs]
    if len(normalized_paragraphs) != len(set(normalized_paragraphs)):
        critical("Обнаружены дословно повторяющиеся абзацы", 15)

    long_paragraphs = [p for p in paragraphs if _word_count(p) > 130]
    if len(long_paragraphs) >= 2:
        warn("Есть несколько перегруженных длинных абзацев", 4)

    short_paragraphs = [p for p in paragraphs if _word_count(p) < 8]
    if len(paragraphs) >= 8 and len(short_paragraphs) / max(1, len(paragraphs)) > 0.35:
        warn("Слишком много рубленых коротких абзацев", 4)

    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 15]
    openings = [" ".join(re.findall(r"\w+", s.lower())[:3]) for s in sentences]
    if openings:
        common = max(openings.count(x) for x in set(openings))
        if common >= 5:
            warn("Слишком однообразные начала предложений", 4)

    if require_ai_audit:
        if not audit:
            critical("Нет независимого AI-аудита качества", 25)
        else:
            verdict = _text(audit.get("verdict")).upper()
            try:
                audit_score = int(float(audit.get("total_score", 0)))
            except (TypeError, ValueError):
                audit_score = 0
            blocking = _items(audit.get("blocking_issues"))
            if verdict != "PASS":
                critical(f"Профессиональный AI-аудитор не допустил материал: {verdict or 'UNKNOWN'}", 25)
            if audit_score < 90:
                critical(f"Оценка AI-аудитора ниже 90: {audit_score}", 20)
            if blocking:
                critical("AI-аудитор нашёл blocking issues: " + "; ".join(blocking[:4]), 25)

    score = max(0, min(100, 100 - deductions))
    ok = not problems and score >= 90
    return {
        "ok": ok,
        "problems": problems,
        "warnings": warnings,
        "words": words,
        "headings": len(headings),
        "score": score,
        "audit_score": (audit or {}).get("total_score") if audit else None,
    }
