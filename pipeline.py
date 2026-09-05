import logging

from ai_writer import generate_article
from analytics import learn_strategy, recommended_categories
from backup import backup_db
from config import ARTICLES_PER_DAY
from db import add_article, add_title_candidates, update_topic_status
from image_generator import make_cover
from publisher import save_to_queue
from quality_checker import check_article
from run_lock import RunLock
from telegram_notify import notify, notify_article
from title_lab import rank_titles
from topic_hunter import collect_topics
from topic_scorer import rank

try:
    from cloud_sync import hydrate_local, sync_local
except Exception:
    hydrate_local = lambda: 0
    sync_local = lambda: 0

log = logging.getLogger(__name__)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _safe(label, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        log.exception("Non-fatal step failed, continuing: %s", label)
        return None


def _provider_fatal(exc: Exception) -> bool:
    text = str(exc).lower()
    infrastructure_markers = (
        "429", "quota", "rate limit", "insufficient_quota", "authentication",
        "unauthorized", "forbidden", "401", "403", "api key", "не задан",
        "не настроен", "недоступен",
    )
    return any(marker in text for marker in infrastructure_markers)


def generate_batch():
    with RunLock():
        _safe("hydrate_local", hydrate_local)
        _safe("backup_db", backup_db)
        learn_strategy()
        topics = rank(collect_topics(max(40, ARTICLES_PER_DAY * 12)))
        preferred = recommended_categories()
        topics = sorted(
            topics,
            key=lambda t: (
                preferred.index(t.get("category", "")) if t.get("category", "") in preferred else 99,
                -float(t.get("score", 0)),
            ),
        )

        made = 0
        attempted = 0
        crashed = 0
        fatal_provider_error = ""
        max_attempts = min(len(topics), max(8, ARTICLES_PER_DAY * 10))

        for topic in topics:
            if made >= ARTICLES_PER_DAY or attempted >= max_attempts:
                break
            attempted += 1
            try:
                data = generate_article(topic)
                chosen = _text(data.get("headline"))
                candidates = rank_titles(data.get("headlines", []), data.get("category", ""))
                quality = check_article(data, require_ai_audit=True)
                log.info(
                    "QUALITY_CHECK headline=%r ok=%s score=%s words=%s headings=%s problems=%s warnings=%s ai_audit_score=%s",
                    chosen,
                    quality.get("ok"),
                    quality.get("score"),
                    quality.get("words"),
                    quality.get("headings"),
                    quality.get("problems"),
                    quality.get("warnings"),
                    quality.get("ai_audit_score"),
                )
                if not quality["ok"]:
                    update_topic_status(topic["id"], "rejected_quality")
                    log.warning("Rejected after professional gate: %s: %s", chosen, quality["problems"])
                    continue

                image = make_cover(chosen, data.get("category", "Авто"))
                path = save_to_queue(data, image)
                aid = add_article(topic["id"], chosen, path, True, "", data.get("category", ""), image, "queued")
                add_title_candidates(aid, candidates, chosen)
                update_topic_status(topic["id"], "used")
                _safe("sync_local", sync_local)

                stages = data.get("ai_stages", [])
                stage_text = " → ".join(_text(x) for x in stages if _text(x))
                audit = data.get("ai_quality_audit", {})
                audit_score = audit.get("total_score", "—")
                header = (
                    f"🚗 Авто без переплаты\nМатериал {made + 1}/{ARTICLES_PER_DAY}\n\n{chosen}\n"
                    f"Категория: {data.get('category', '')}\nПроверка: ✅ PROFESSIONAL PASS\n"
                    f"Quality gate: {quality['score']}/100\nНезависимый AI-аудит: {audit_score}/100\n"
                    f"Слов: {quality['words']}\nПодзаголовков: {quality.get('headings', '—')}\n"
                    f"AI-цепочка: {stage_text}\nИсточников: {len(data.get('source_urls', []))}\nID: {aid}"
                )
                message_ids = notify_article(header, data.get("article_markdown", ""))
                if not message_ids:
                    raise RuntimeError("Telegram не подтвердил доставку статьи")
                log.info(
                    "ARTICLE_ACCEPTED id=%s headline=%r quality_score=%s ai_audit_score=%s telegram_message_ids=%s path=%s",
                    aid, chosen, quality.get("score"), audit_score, message_ids, path,
                )
                made += 1
            except Exception as exc:
                crashed += 1
                update_topic_status(topic["id"], "error")
                log.exception("Topic failed: %s", topic.get("title"))
                if _provider_fatal(exc):
                    fatal_provider_error = str(exc)
                    log.error("Stopping batch after provider-level failure: %s", fatal_provider_error)
                    break

        learn_strategy()
        _safe("sync_local", sync_local)
        if made == 0:
            if fatal_provider_error:
                notify(
                    "⚠️ Авто без переплаты: генерация остановлена на уровне AI-провайдера после "
                    f"{attempted} попытки. Причина: {fatal_provider_error[:900]}"
                )
            elif crashed >= attempted and attempted > 0:
                notify(
                    "⚠️ Авто без переплаты: ни одной статьи не создано — все попытки упали "
                    f"с ошибкой ДО проверки качества, попыток: {attempted}."
                )
            else:
                notify("⚠️ Авто без переплаты: ни один материал не прошёл professional quality gate. Брак не отправлен и не поставлен в публикацию.")
        return made
