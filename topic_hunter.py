import re, html, datetime as dt
import feedparser
from config import RSS_SOURCES
from db import add_topic, topic_seen

AUTO_WORDS=['автомобиль','авто','машин','кроссовер','седан','внедорожник','двигател','коробк','шина','тормоз','масл','аккумулятор','электромобил','гибрид','китайск','toyota','lexus','bmw','mercedes','kia','hyundai','haval','chery','geely','changan','lada','уаз','nissan','honda','volkswagen','audi','car','vehicle','suv','sedan','engine','transmission','tire','brake','battery','electric','hybrid','ford','tesla','mazda','subaru','volvo','porsche']
NEWS_ONLY=['скандал','авар','катастроф','жертв','политик','войн','криминал']


def clean(s):
    s=re.sub('<[^>]+>',' ',s or '')
    return html.unescape(re.sub(r'\s+',' ',s)).strip()


def score(title,summary,age_hours=12):
    t=(title+' '+summary).lower(); s=0
    s+=max(0,20-age_hours)*1.2
    s+=sum(3 for w in AUTO_WORDS if w in t)
    s+=sum(5 for w in ['купить','покупк','расход','ремонт','обслуж','стоимость','цена','провер','сравн','надёж','переплат','buy','price','cost','repair','maintenance','reliab','review','compare'] if w in t)
    s-=sum(12 for w in NEWS_ONLY if w in t)
    if any(x in t for x in ['цена','расход','ремонт','обслуж','купить','провер','price','cost','repair','maintenance','buy']): s+=12
    return round(s,2)


def collect_topics(limit=40):
    candidates=[]
    diagnostics=[]
    for url in RSS_SOURCES:
        feed=feedparser.parse(url)
        entries=list(getattr(feed,'entries',[]) or [])
        bozo_exc=getattr(feed,'bozo_exception',None)
        diagnostics.append(f'{url}: entries={len(entries)} bozo={getattr(feed,"bozo",0)} bozo_exception={bozo_exc!r}')
        source=feed.feed.get('title',url)
        skipped_bad=0
        for e in entries[:100]:
            try:
                title=clean(getattr(e,'title','')); link=clean(getattr(e,'link','')); summary=clean(getattr(e,'summary',''))
                if not title or topic_seen(title): continue
                if not link.startswith(('http://','https://')): continue
                text=(title+' '+summary).lower()
                if not any(w in text for w in AUTO_WORDS): continue
                published=getattr(e,'published_parsed',None)
                age=12
                if published:
                    try: age=max(0,(dt.datetime.now(dt.timezone.utc)-dt.datetime(*published[:6],tzinfo=dt.timezone.utc)).total_seconds()/3600)
                    except Exception: pass
                candidates.append((score(title,summary,age),title,link,source,summary))
            except Exception as exc:
                skipped_bad += 1
                diagnostics.append(f'{url}: skipped malformed item error={exc!r}')
        if skipped_bad:
            diagnostics.append(f'{url}: skipped_bad_entries={skipped_bad}')
    candidates.sort(reverse=True,key=lambda x:x[0])
    out=[]
    for sc,title,link,source,summary in candidates[:limit]:
        tid=add_topic(title,link,source,summary,sc)
        out.append({'id':tid,'title':title,'link':link,'source':source,'summary':summary,'score':sc})
    print('topic_hunter:', '; '.join(diagnostics), 'accepted=', len(out))
    return out
