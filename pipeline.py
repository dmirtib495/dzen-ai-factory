import logging
from topic_hunter import collect_topics
from topic_scorer import rank
from ai_writer import generate_article
from quality_checker import check_article
from publisher import save_to_queue
from image_generator import make_cover
from telegram_notify import notify
from config import ARTICLES_PER_DAY
from db import add_article, add_title_candidates, update_topic_status
from analytics import learn_strategy, recommended_categories
from title_lab import rank_titles
from run_lock import RunLock
from backup import backup_db
try:
    from cloud_sync import hydrate_local, sync_local
except Exception:
    hydrate_local = lambda: 0
    sync_local = lambda: 0

log=logging.getLogger(__name__)

def generate_batch():
    with RunLock():
        hydrate_local(); backup_db(); learn_strategy()
        topics=rank(collect_topics(max(40,ARTICLES_PER_DAY*12)))
        preferred=recommended_categories()
        # Give learned categories a deterministic bonus without requiring another AI call.
        topics=sorted(topics,key=lambda t:(preferred.index(t.get('category','')) if t.get('category','') in preferred else 99, -float(t.get('score',0))))
        made=0
        for topic in topics:
            if made>=ARTICLES_PER_DAY: break
            try:
                data=generate_article(topic)
                candidates=rank_titles(data.get('headlines',[]),data.get('category',''))
                chosen=candidates[0]['title'] if candidates else data['headline']
                data['headline']=chosen
                q=check_article(data)
                if not q['ok']:
                    status='needs_review'
                else: status='queued'
                image=make_cover(chosen,data.get('category','Авто'))
                path=save_to_queue(data,image)
                aid=add_article(topic['id'],chosen,path,q['ok'],'; '.join(q['problems']),data.get('category',''),image,status)
                add_title_candidates(aid,candidates,chosen)
                update_topic_status(topic['id'],'used')
                sync_local()
                notify(f'''🚗 Авто без переплаты\nМатериал {made+1}/{ARTICLES_PER_DAY}\n\n{chosen}\nКатегория: {data.get('category','')}\nПроверка: {'OK' if q['ok'] else 'НУЖНА ПРОВЕРКА'}\nСлов: {q['words']}\nAI сегодня: запрос зарезервирован\nID: {aid}\nФайл: {path}''')
                made+=1
            except Exception as e:
                update_topic_status(topic['id'],'error'); log.exception('Topic failed: %s',topic.get('title'))
                notify(f'❌ Ошибка по теме «{topic.get("title","")}: {e}')
        learn_strategy(); sync_local(); return made
