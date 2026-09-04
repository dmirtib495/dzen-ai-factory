import csv, json
from pathlib import Path
from db import add_metric, connect
from title_lab import rank_titles

CATEGORIES=['Что купить','Стоит ли брать','Экономия','Сравнения','Авто-технологии']
STRATEGY_PATH=Path('data/strategy.json')

def import_metrics(path):
    path=Path(path); n=0
    if path.suffix.lower()=='.json':
        rows=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(rows,dict): rows=rows.get('articles',[])
    else:
        with path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    for row in rows:
        aid=int(row['article_id']); add_metric(aid,int(row.get('views',0)),int(row.get('likes',0)),int(row.get('comments',0)),int(row.get('shares',0)),'import'); n+=1
    return n

def article_performance():
    c=connect(); rows=c.execute('''SELECT a.id,a.title,a.category,COALESCE(SUM(m.views),0),COALESCE(SUM(m.likes),0),COALESCE(SUM(m.comments),0),COALESCE(SUM(m.shares),0)
    FROM articles a LEFT JOIN metrics m ON m.article_id=a.id GROUP BY a.id ORDER BY a.id DESC''').fetchall(); c.close()
    out=[]
    for aid,title,cat,v,l,co,s in rows:
        er=(l+co*2+s*3)/max(v,1)*100
        out.append({'article_id':aid,'title':title,'category':cat or 'Разбор','views':v,'likes':l,'comments':co,'shares':s,'engagement':round(er,3)})
    return out

def learn_strategy():
    rows=article_performance(); by={c:{'articles':0,'views':0,'engagement':0} for c in CATEGORIES}
    for r in rows:
        x=by.setdefault(r['category'],{'articles':0,'views':0,'engagement':0}); x['articles']+=1; x['views']+=r['views']; x['engagement']+=r['engagement']
    for x in by.values():
        x['avg_views']=round(x['views']/max(x['articles'],1),1); x['avg_engagement']=round(x['engagement']/max(x['articles'],1),3)
    # Exploration bonus prevents a new category from being starved forever.
    max_views=max([x['avg_views'] for x in by.values()] or [1])
    for k,x in by.items():
        base=0.7+0.3*(x['avg_views']/max_views if max_views else 0)
        if x['articles']==0: base+=0.5
        x['weight']=round(base,3)
    strategy={'categories':by,'updated_articles':len(rows)}
    STRATEGY_PATH.parent.mkdir(parents=True,exist_ok=True); STRATEGY_PATH.write_text(json.dumps(strategy,ensure_ascii=False,indent=2),encoding='utf-8')
    c=connect();
    for k,x in by.items(): c.execute('INSERT INTO strategy(category,weight,articles,avg_views,avg_engagement) VALUES(?,?,?,?,?) ON CONFLICT(category) DO UPDATE SET weight=excluded.weight,articles=excluded.articles,avg_views=excluded.avg_views,avg_engagement=excluded.avg_engagement,updated_at=CURRENT_TIMESTAMP',(k,x['weight'],x['articles'],x['avg_views'],x['avg_engagement']))
    c.commit(); c.close(); return strategy

def get_strategy():
    try:
        if STRATEGY_PATH.exists(): return json.loads(STRATEGY_PATH.read_text(encoding='utf-8'))
    except Exception: pass
    return learn_strategy()

def recommended_categories():
    st=get_strategy(); return sorted(st.get('categories',{}),key=lambda k:st['categories'][k].get('weight',1),reverse=True)

def top_articles(limit=5): return sorted(article_performance(),key=lambda x:(x['views'],x['engagement']),reverse=True)[:limit]
