from pathlib import Path
from datetime import datetime
import json, os, uuid
from config import ARTICLES_DIR, OUTBOX_DIR
QUEUE=ARTICLES_DIR; OUTBOX=OUTBOX_DIR

def save_to_queue(data,image_path=''):
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:6]
    p=QUEUE/(stamp+'.md')
    checks='\n'.join('- '+x for x in data.get('fact_check',[])) or '- Нет отдельных пунктов'
    sources='\n'.join('- '+x for x in data.get('source_urls',[])) or '- Источник темы указан в метаданных; проверить перед публикацией.'
    text=f'''# {data['headline']}\n\n{data.get('article_markdown','').strip()}\n\n## Что проверить перед публикацией\n{checks}\n\n## Источники\n{sources}\n\n## Изображение\n{image_path}\n'''
    p.write_text(text,encoding='utf-8')
    manifest={'headline':data['headline'],'category':data.get('category',''),'article_markdown':data.get('article_markdown','').strip(),'source_urls':data.get('source_urls',[]),'fact_check':data.get('fact_check',[]),'image_path':str(image_path),'created_at':datetime.now().isoformat(timespec='seconds'),'status':'queued'}
    (OUTBOX/(stamp+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return p

def publish(path):
    endpoint=os.getenv('ZEN_PUBLISH_ENDPOINT','').strip()
    if not endpoint: raise RuntimeError('Публикация не настроена: материал оставлен в outbox для ручной публикации через поддерживаемый интерфейс Дзена.')
    raise RuntimeError('Автоматическая публикация не включена: универсальный официальный API-контракт не подтверждён.')
