import json, os, sqlite3
from pathlib import Path
import requests
from config import DB_PATH, OUTBOX_DIR

API='https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query'

def enabled():
    return all(os.getenv(k,'').strip() for k in ('CLOUDFLARE_API_TOKEN','CLOUDFLARE_ACCOUNT_ID','CLOUDFLARE_D1_DATABASE_ID'))

def query(sql, params=None):
    if not enabled(): return None
    url=API.format(account=os.environ['CLOUDFLARE_ACCOUNT_ID'],db=os.environ['CLOUDFLARE_D1_DATABASE_ID'])
    r=requests.post(url,headers={'Authorization':f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}",'Content-Type':'application/json'},json={'sql':sql,'params':params or []},timeout=30)
    r.raise_for_status(); data=r.json()
    if not data.get('success'): raise RuntimeError(str(data))
    return data['result'][0]

def init_schema(schema_path=None):
    schema_path=Path(schema_path or Path(__file__).parent/'cloud/schema.sql')
    sql=schema_path.read_text(encoding='utf-8')
    return query(sql)

def hydrate_local():
    if not enabled(): return 0
    import sqlite3
    c=sqlite3.connect(DB_PATH)
    result=query("SELECT id,headline,category,status,quality_ok,created_at FROM articles ORDER BY id") or {}
    rows=result.get('results',[])
    for r in rows:
        c.execute("INSERT OR IGNORE INTO articles(id,topic_id,title,path,image_path,quality_ok,quality_notes,category,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", [r.get('id'),None,r.get('headline',''),'','','' if False else int(r.get('quality_ok',0)),'',r.get('category',''),r.get('status','queued'),r.get('created_at')])
        c.execute("UPDATE articles SET title=?,category=?,status=?,quality_ok=?,created_at=? WHERE id=?", [r.get('headline',''),r.get('category',''),r.get('status','queued'),int(r.get('quality_ok',0)),r.get('created_at'),r.get('id')])
    result=query("SELECT article_id,views,likes,comments,shares,updated_at FROM metrics") or {}
    for r in result.get('results',[]):
        c.execute("INSERT OR REPLACE INTO metrics(article_id,views,likes,comments,shares,source,created_at) VALUES(?,?,?,?,?,?,?)", [r.get('article_id'),r.get('views',0),r.get('likes',0),r.get('comments',0),r.get('shares',0),'cloud',r.get('updated_at')])
    c.commit(); c.close(); return len(rows)

def sync_local():
    if not enabled(): return 0
    c=sqlite3.connect(DB_PATH)
    articles=c.execute('SELECT id,title,category,quality_ok,status,created_at FROM articles').fetchall()
    n=0
    for aid,title,cat,qok,status,created in articles:
        manifest=None
        for p in OUTBOX_DIR.glob('*.json'):
            try:
                x=json.loads(p.read_text(encoding='utf-8'))
                if x.get('headline')==title: manifest=x; break
            except Exception: pass
        if not manifest: continue
        now=created or ''
        query('''INSERT INTO articles(id,headline,category,article_markdown,source_urls_json,fact_check_json,image_url,status,quality_ok,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET headline=excluded.headline,category=excluded.category,article_markdown=excluded.article_markdown,source_urls_json=excluded.source_urls_json,fact_check_json=excluded.fact_check_json,image_url=excluded.image_url,status=excluded.status,quality_ok=excluded.quality_ok,updated_at=excluded.updated_at''',
        [aid,title,cat or '',manifest.get('article_markdown',''),json.dumps(manifest.get('source_urls',[]),ensure_ascii=False),json.dumps(manifest.get('fact_check',[]),ensure_ascii=False),manifest.get('image_url'),status,int(qok),now,now])
        n+=1
    # Persist learned category strategy for the Telegram Worker.
    try:
        rows=c.execute('SELECT category,weight,articles,avg_views,avg_engagement FROM strategy').fetchall()
        strategy={'categories':{r[0]:{'weight':r[1],'articles':r[2],'avg_views':r[3],'avg_engagement':r[4]} for r in rows},'updated_articles':sum(r[2] for r in rows)}
        query("INSERT INTO settings(key,value,updated_at) VALUES('strategy',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", [json.dumps(strategy,ensure_ascii=False), __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()])
    except Exception:
        pass
    c.close(); return n

if __name__=='__main__':
    print('Cloud hydrate:', hydrate_local() if enabled() else 'disabled'); print('Cloud sync:', sync_local() if enabled() else 'disabled')
