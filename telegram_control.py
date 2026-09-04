import json, time, logging
from pathlib import Path
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from db import list_recent
from analytics import learn_strategy, top_articles
from pipeline import generate_batch
from approval import list_pending, approve, reject
from quota import status as quota_status

log=logging.getLogger(__name__); OUTBOX=Path('data/publish_outbox')

class ControlBot:
    def __init__(self): self.running=False; self.offset=0; self.base=f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'
    def api(self,method,**kwargs):
        r=requests.post(f'{self.base}/{method}',timeout=35,**kwargs); r.raise_for_status(); return r.json()
    def send(self,chat,text,reply_markup=None):
        payload={'chat_id':chat,'text':text[:4096]}
        if reply_markup: payload['reply_markup']=json.dumps(reply_markup,ensure_ascii=False)
        return self.api('sendMessage',json=payload)
    def send_photo(self,chat,image_path,caption,reply_markup=None):
        if not image_path or not Path(image_path).exists(): return self.send(chat,caption,reply_markup)
        data={'chat_id':chat,'caption':caption[:1024]}
        if reply_markup: data['reply_markup']=json.dumps(reply_markup,ensure_ascii=False)
        with open(image_path,'rb') as f: return self.api('sendPhoto',data=data,files={'photo':f})
    def menu(self):
        return {'inline_keyboard':[[{'text':'📋 Очередь','callback_data':'queue'},{'text':'📊 Аналитика','callback_data':'analytics'}],[{'text':'🧠 Стратегия','callback_data':'strategy'},{'text':'📈 Лимит AI','callback_data':'quota'}],[{'text':'🚗 Создать 3 статьи','callback_data':'generate'},{'text':'🔄 Обновить','callback_data':'status'}]]}
    def manifest(self,name):
        p=OUTBOX/name; return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None
    def queue_text(self):
        items=list_pending()
        if not items:return '📭 Очередь пуста.'
        return '📋 Очередь:\n'+'\n'.join(f"• {p.stem} — {(self.manifest(p.name) or {}).get('headline','без заголовка')}" for p in items[:10])
    def send_review(self,chat,p):
        m=self.manifest(p.name)
        if not m:return self.send(chat,'Материал уже обработан.')
        kb={'inline_keyboard':[[{'text':'✅ Одобрить','callback_data':'approve:'+p.name},{'text':'❌ Отклонить','callback_data':'reject:'+p.name}],[{'text':'📄 Текст','callback_data':'text:'+p.name}]]}
        self.send_photo(chat,m.get('image_path',''),f"🚗 {m.get('headline','')}\n\nКатегория: {m.get('category','')}\n\nПроверь материал перед публикацией.",kb)
    def handle_callback(self,chat,data,callback_id):
        if callback_id: self.api('answerCallbackQuery',json={'callback_query_id':callback_id})
        if data=='queue':
            self.send(chat,self.queue_text(),self.menu()); items=list_pending();
            if items:self.send_review(chat,items[0])
        elif data=='analytics':
            top=top_articles(5); body=['📊 Топ материалов']+[f"• {x['views']} просмотров | ER {x['engagement']}% | {x['title']}" for x in top]
            self.send(chat,'\n'.join(body) if top else 'Пока нет статистики.',self.menu())
        elif data=='strategy':
            st=learn_strategy(); body=['🧠 Стратегия категорий']+[f"• {k}: вес {v['weight']} | статей {v['articles']} | ср. просмотры {v['avg_views']}" for k,v in sorted(st['categories'].items(),key=lambda x:x[1]['weight'],reverse=True)]
            self.send(chat,'\n'.join(body),self.menu())
        elif data=='quota':
            q=quota_status(); self.send(chat,f"📈 OpenRouter\nИспользовано сегодня: {q['used']}\nОсталось: {q['remaining']}\nЛимит: {q['limit']}",self.menu())
        elif data=='status':
            q=quota_status(); self.send(chat,f"🟢 Фабрика v1.0\nВ очереди: {len(list_pending())}\nПоследние: {len(list_recent(10))}\nAI: {q['used']}/{q['limit']}",self.menu())
        elif data=='generate': self._generate(chat)
        elif data.startswith('approve:'):
            try:self.send(chat,f'✅ Одобрено: {approve(OUTBOX/data.split(":",1)[1]).name}\nПубликация остаётся отдельным официальным шагом.',self.menu())
            except Exception as e:self.send(chat,f'❌ {e}')
        elif data.startswith('reject:'):
            try:self.send(chat,f'❌ Отклонено: {reject(OUTBOX/data.split(":",1)[1]).name}',self.menu())
            except Exception as e:self.send(chat,f'❌ {e}')
        elif data.startswith('text:'):
            m=self.manifest(data.split(':',1)[1]); self.send(chat,f"📝 {m.get('headline','')}\n\n{m.get('article_markdown','')[:3800]}",self.menu()) if m else self.send(chat,'Материал не найден.')
    def _generate(self,chat):
        if self.running:return self.send(chat,'⏳ Генерация уже выполняется.')
        self.running=True; self.send(chat,'⏳ Запускаю генерацию...')
        try:self.send(chat,f'✅ Создано: {generate_batch()} материалов.',self.menu())
        except Exception as e:self.send(chat,f'❌ {e}',self.menu())
        finally:self.running=False
    def loop(self):
        if not TELEGRAM_BOT_TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN не задан')
        while True:
            try:
                r=requests.get(f'{self.base}/getUpdates',params={'timeout':25,'offset':self.offset},timeout=35).json()
                for u in r.get('result',[]):
                    self.offset=u['update_id']+1
                    if 'callback_query' in u:
                        cb=u['callback_query']; chat=str(cb.get('message',{}).get('chat',{}).get('id',''))
                        if TELEGRAM_CHAT_ID and chat!=str(TELEGRAM_CHAT_ID):continue
                        self.handle_callback(chat,cb.get('data',''),cb['id']); continue
                    m=u.get('message',{}); chat=str(m.get('chat',{}).get('id','')); txt=m.get('text','')
                    if TELEGRAM_CHAT_ID and chat!=str(TELEGRAM_CHAT_ID):continue
                    if txt in ('/start','/help'):self.send(chat,'🤖 Dzen AI Factory v1.0\nУправление фабрикой:',self.menu())
                    elif txt=='/queue':self.send(chat,self.queue_text(),self.menu())
                    elif txt=='/status':self.handle_callback(chat,'status','0')
                    elif txt=='/analytics':self.handle_callback(chat,'analytics','0')
                    elif txt=='/strategy':self.handle_callback(chat,'strategy','0')
                    elif txt=='/limits':self.handle_callback(chat,'quota','0')
                    elif txt=='/generate':self._generate(chat)
            except Exception as e: log.exception('Telegram loop error: %s',e); time.sleep(5)
