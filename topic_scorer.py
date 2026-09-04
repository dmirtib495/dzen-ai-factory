from analytics import get_strategy

COMMERCIAL=['купить','цена','расход','обслуживание','ремонт','запчаст','надёж','проверить','сравнить','выгод','переплат','стоимость']
PRACTICAL=['как','чек-лист','ошибк','ресурс','проблем','срок','зимой','летом','масло','шины','тормоз','коробк','двигател']

def rank(topics):
    strategy=get_strategy().get('categories',{})
    def key(t):
        text=(t['title']+' '+t.get('summary','')).lower()
        bonus=sum(4 for w in COMMERCIAL if w in text)+sum(2 for w in PRACTICAL if w in text)
        evergreen=8 if t.get('source')=='evergreen' else 0
        learned=0
        # Previous winners influence future topic selection without extra AI calls.
        for cat,stats in strategy.items():
            if cat.lower() in text:
                learned += min(20, stats.get('avg_views',0)/1000) + min(10,stats.get('avg_engagement',0)*2)
        return t.get('score',0)+bonus+evergreen+learned
    ranked=sorted(topics,key=key,reverse=True)
    # Keep category diversity in each batch.
    result=[]; cats={}
    for t in ranked:
        cat=t.get('source') if t.get('source')=='evergreen' else 'news'
        if len(result)<3 or cats.get(cat,0)<2:
            result.append(t); cats[cat]=cats.get(cat,0)+1
    for t in ranked:
        if t not in result: result.append(t)
    return result
