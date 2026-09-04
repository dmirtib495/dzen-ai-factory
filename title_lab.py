import re

def score_title(title, category=''):
    t=title.strip(); s=50.0
    n=len(t)
    if 45 <= n <= 90: s+=20
    elif 30 <= n <= 110: s+=10
    else: s-=10
    if re.search(r'\b(как|стоит|почему|сколько|5|7|10|ошиб|расход|ремонт|провер|купить|сравн)\b',t,re.I): s+=15
    if '?' in t: s+=5
    if re.search(r'100%|гарант|лучший|самый лучший|никогда|всегда',t,re.I): s-=30
    if re.search(r'[!]{2,}',t): s-=10
    if category and category.lower() in t.lower(): s+=3
    return round(max(0,min(100,s)),2)

def rank_titles(candidates, category=''):
    out=[]; seen=set()
    for t in candidates or []:
        if not isinstance(t,str): continue
        key=re.sub(r'\W+',' ',t.lower()).strip()
        if not key or key in seen: continue
        seen.add(key); out.append({'title':t.strip(),'score':score_title(t,category)})
    return sorted(out,key=lambda x:x['score'],reverse=True)
