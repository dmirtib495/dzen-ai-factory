import re,html,datetime as dt
import feedparser
from config import RSS_SOURCES
from db import add_topic,topic_seen

AUTO_WORDS=['автомобиль','авто','машин','кроссовер','седан','внедорожник','двигател','коробк','шина','тормоз','масл','аккумулятор','электромобил','гибрид','китайск','toyota','lexus','bmw','mercedes','kia','hyundai','haval','chery','geely','changan','lada','уаз','nissan','honda','volkswagen','audi']
NEWS_ONLY=['скандал','авар','катастроф','жертв','политик','войн','криминал']
EVERGREEN=[
 'Как проверить подержанный автомобиль перед покупкой: чек-лист без лишних расходов',
 'Какие расходы на автомобиль чаще всего забывают посчитать перед покупкой',
 'Когда замена масла действительно нужна раньше регламента и когда это лишняя трата',
 'Как понять, что автоматическая коробка передач скоро потребует ремонта',
 'Какие опции автомобиля реально полезны каждый день, а за какие не стоит переплачивать',
 'Как выбрать семейный кроссовер: что проверить кроме размера багажника',
 'Почему дорогая машина с большим пробегом может оказаться выгоднее дешёвой',
 'Что проверить в автомобиле после зимы, чтобы не попасть на крупный ремонт'
]

def clean(s):
    s=re.sub('<[^>]+>',' ',s or ''); return html.unescape(re.sub(r'\s+',' ',s)).strip()

def score(title,summary,age_hours=12):
    t=(title+' '+summary).lower(); s=0
    s+=max(0,20-age_hours)*1.2
    s+=sum(3 for w in AUTO_WORDS if w in t)
    s+=sum(5 for w in ['купить','покупк','расход','ремонт','обслуж','стоимость','цена','провер','сравн','надёж','переплат'] if w in t)
    s-=sum(12 for w in NEWS_ONLY if w in t)
    if any(x in t for x in ['цена','расход','ремонт','обслуж','купить','провер']): s+=12
    return round(s,2)

def collect_topics(limit=40):
    candidates=[]
    for url in RSS_SOURCES:
        feed=feedparser.parse(url)
        source=feed.feed.get('title',url)
        for e in getattr(feed,'entries',[])[:50]:
            title=clean(getattr(e,'title','')); link=getattr(e,'link',''); summary=clean(getattr(e,'summary',''))
            if not title or topic_seen(title): continue
            text=(title+' '+summary).lower()
            if not any(w in text for w in AUTO_WORDS): continue
            published=getattr(e,'published_parsed',None)
            age=12
            if published:
                try: age=max(0,(dt.datetime.now(dt.timezone.utc)-dt.datetime(*published[:6],tzinfo=dt.timezone.utc)).total_seconds()/3600)
                except Exception: pass
            candidates.append((score(title,summary,age),title,link,source,summary))
    for title in EVERGREEN:
        if not topic_seen(title): candidates.append((18,title,'','evergreen','Практическая вечнозелёная тема канала.'))
    candidates.sort(reverse=True,key=lambda x:x[0])
    out=[]
    for sc,title,link,source,summary in candidates[:limit]:
        tid=add_topic(title,link,source,summary,sc)
        out.append({'id':tid,'title':title,'link':link,'source':source,'summary':summary,'score':sc})
    return out
