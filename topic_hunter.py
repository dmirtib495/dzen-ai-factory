import datetime as dt
import html
import html.entities
import re

import feedparser
import requests

from config import RSS_SOURCES
from db import add_topic, topic_seen
from dzen_trends import best_trend_match, fetch_auto_trends

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
    """Return valid UTF-8 XML bytes after repairing illegal HTML entities/encoding."""
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
        response=requests.get(url,timeout=30,headers={'User-Agent':'dzen-ai-factory/2.0'})
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


def _load_dzen_trends(diagnostics: list[str]):
    """Best-effort popularity signal; RSS remains a safe factual-source fallback."""
    try:
        trends=fetch_auto_trends(top_channels=8,posts_per_channel=12,period=30,limit=60)
        diagnostics.append(f'dzen_trends: loaded={len(trends)}')
        if trends:
            leaders=', '.join(f'{x.channel_title}:{x.views}' for x in trends[:5])
            diagnostics.append(f'dzen_trends leaders={leaders}')
        return trends
    except Exception as exc:
        diagnostics.append(f'dzen_trends unavailable={exc!r}; using RSS-only fallback')
        return []


def collect_topics(limit=40):
    candidates=[]
    diagnostics=[]
    trends=_load_dzen_trends(diagnostics)

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

                base_score=score(title,summary,age)
                trend,trend_rel,trend_bonus=best_trend_match(title,trends)
                final_score=round(base_score+trend_bonus,2)
                candidates.append({
                    'score':final_score,
                    'base_score':base_score,
                    'title':title,
                    'link':link,
                    'source':source,
                    'summary':summary,
                    # Trend metadata is selection telemetry only. ai_writer uses
                    # link/summary above as factual evidence and never treats the
                    # competitor Dzen page as a read source.
                    'trend_title':trend.title if trend else '',
                    'trend_url':trend.url if trend else '',
                    'trend_views':trend.views if trend else 0,
                    'trend_channel':trend.channel_title if trend else '',
                    'trend_channel_views30days':trend.channel_views30days if trend else 0,
                    'trend_relevance':round(trend_rel,3),
                    'trend_bonus':trend_bonus,
                })
            except Exception as exc:
                skipped_bad += 1
                diagnostics.append(f'{url}: skipped malformed item error={exc!r}')
        if skipped_bad:
            diagnostics.append(f'{url}: skipped_bad_entries={skipped_bad}')

    candidates.sort(reverse=True,key=lambda x:x['score'])
    out=[]
    for item in candidates[:limit]:
        tid=add_topic(item['title'],item['link'],item['source'],item['summary'],item['score'])
        item=dict(item)
        item['id']=tid
        out.append(item)

    trend_matches=[x for x in out if x.get('trend_url')]
    diagnostics.append(f'dzen_trend_matches_in_output={len(trend_matches)}/{len(out)}')
    for x in trend_matches[:5]:
        diagnostics.append(
            f"trend_match rss={x['title']!r} <- dzen={x['trend_title']!r} "
            f"views={x['trend_views']} channel={x['trend_channel']!r} bonus={x['trend_bonus']}"
        )
    print('topic_hunter:', '; '.join(diagnostics), 'accepted=', len(out))
    return out
