import datetime as dt
import html
import html.entities
import re

import feedparser
import requests

from config import RSS_SOURCES
from db import add_topic, topic_seen

AUTO_WORDS=['автомобиль','авто','машин','кроссовер','седан','внедорожник','двигател','коробк','шина','тормоз','масл','аккумулятор','электромобил','гибрид','китайск','toyota','lexus','bmw','mercedes','kia','hyundai','haval','chery','geely','changan','lada','уаз','nissan','honda','volkswagen','audi','car','vehicle','suv','sedan','engine','transmission','tire','brake','battery','electric','hybrid','ford','tesla','mazda','subaru','volvo','porsche']
NEWS_ONLY=['скандал','авар','катастроф','жертв','политик','войн','криминал']
XML_PREDEFINED={'amp','lt','gt','quot','apos'}
ENTITY_RE=re.compile(r'&([A-Za-z][A-Za-z0-9]+);')
XML_ENCODING_RE=re.compile(r'(<\?xml[^>]*\bencoding=["\'])[^"\']+(["\'])', re.I)


def clean(s):
    s=re.sub('<[^>]+>',' ',s or '')
    return html.unescape(re.sub(r'\s+',' ',s)).strip()


def _xml_safe_named_entities(text: str) -> str:
    """Convert HTML named entities that are illegal in XML RSS to numeric refs."""
    def repl(match):
        name=match.group(1)
        if name in XML_PREDEFINED:
            return match.group(0)
        codepoint=html.entities.name2codepoint.get(name)
        return f'&#{codepoint};' if codepoint else match.group(0)
    return ENTITY_RE.sub(repl,text)


def _sanitized_xml_bytes(response) -> bytes:
    """Return valid UTF-8 XML bytes after repairing illegal HTML entities.

    Some Drom RSS documents declare windows-1251 while requests decodes the
    response to Unicode. Passing that Unicode back to feedparser with the old
    declaration produces CharacterEncodingOverride/bozo even after the entity
    error is fixed. We therefore decode once, repair entities, rewrite the XML
    declaration to UTF-8, and pass matching UTF-8 bytes to the parser.
    """
    encoding=(response.encoding or 'windows-1251').strip() or 'windows-1251'
    try:
        text=response.content.decode(encoding, errors='strict')
    except (LookupError, UnicodeDecodeError):
        text=response.content.decode('windows-1251', errors='replace')
    text=_xml_safe_named_entities(text)
    text=XML_ENCODING_RE.sub(r'\1utf-8\2', text, count=1)
    return text.encode('utf-8')


def _parse_feed(url: str):
    """Fetch RSS explicitly, repair invalid entities/encoding, then parse."""
    try:
        response=requests.get(url,timeout=30,headers={'User-Agent':'dzen-ai-factory/1.0'})
        response.raise_for_status()
        return feedparser.parse(_sanitized_xml_bytes(response))
    except Exception:
        return feedparser.parse(url)


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
        feed=_parse_feed(url)
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
