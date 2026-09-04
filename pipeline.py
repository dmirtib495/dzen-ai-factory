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
from telegram_notify import notify
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
    if value is None: return ""
    if isinstance(value, str): return value.strip()
    return str(value).strip()


def generate_batch():
    with RunLock():
        hydrate_local(); backup_db(); learn_strategy()
        topics = rank(collect_topics(max(40, ARTICLES_PER_DAY * 12)))
        preferred = recommended_categories()
        topics = sorted(topics, key=lambda t: (preferred.index(t.get("category", "")) if t.get("category", "") in preferred else 99, -float(t.get("score", 0))))
        made = 0
        for topic in topics:
            if made >= ARTICLES_PER_DAY: break
            try:
                data = generate_article(topic)
                candidates = rank_titles(data.get("headlines", []), data.get("category", ""))
                chosen = candidates[0]["title"] if candidates else data["headline"]
                data["headline"] = chosen
                quality = check_article(data)
                status = "queued" if quality["ok"] else "needs_review"
                image = make_cover(chosen, data.get("category", "Авто"))
                path = save_to_queue(data, image)
                aid = add_article(topic["id"], chosen, path, quality["ok"], "; ".join(quality["problems"]), data.get("category", ""), image, status)
                add_title_candidates(aid, candidates, chosen); update_topic_status(topic["id"], "used"); sync_local()
                stages = data.get("ai_stages", [])
                stage_text = " → ".join(_text(x) for x in stages if _text(x)) or f"{_text(data.get('ai_provider'))}:{_text(data.get('ai_model'))}"
                problems = "; ".join(quality["problems"]) or "нет"
                notify(f"🚗 Авто без переплаты\nМатериал {made + 1}/{ARTICLES_PER_DAY}\n\n{chosen}\nКатегория: {data.get('category', '')}\nПроверка: {'OK' if quality['ok'] else 'НУЖНА ПРОВЕРКА'}\nКачество: {quality['score']}/100\nСлов: {quality['words']}\nПроблемы: {problems}\nAI-цепочка: {stage_text}\nИсточников: {len(data.get('source_urls', []))}\nID: {aid}\nФайл: {path}")
                made += 1
            except Exception as exc:
                update_topic_status(topic["id"], "error"); log.exception("Topic failed: %s", topic.get("title")); notify(f"❌ Ошибка по теме «{topic.get('title', '')}»: {exc}")
        learn_strategy(); sync_local(); return made
