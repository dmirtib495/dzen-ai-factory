import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from config import DB_PATH

SCHEMA_VERSION = 2

def connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    migrate(c)
    return c

def migrate(c):
    c.execute('CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    row = c.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    version = int(row[0]) if row else 0
    c.execute('''CREATE TABLE IF NOT EXISTS topics(
      id INTEGER PRIMARY KEY,title TEXT UNIQUE,link TEXT,source TEXT,summary TEXT,
      score REAL DEFAULT 0,status TEXT DEFAULT 'new',created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS articles(
      id INTEGER PRIMARY KEY,topic_id INTEGER,title TEXT,path TEXT,image_path TEXT,
      quality_ok INTEGER,quality_notes TEXT,category TEXT,status TEXT DEFAULT 'queued',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(topic_id) REFERENCES topics(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS metrics(
      id INTEGER PRIMARY KEY,article_id INTEGER,views INTEGER DEFAULT 0,likes INTEGER DEFAULT 0,
      comments INTEGER DEFAULT 0,shares INTEGER DEFAULT 0,source TEXT DEFAULT 'manual',created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(article_id) REFERENCES articles(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS ai_usage(
      day TEXT PRIMARY KEY,requests INTEGER DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS strategy(
      category TEXT PRIMARY KEY,weight REAL NOT NULL DEFAULT 1.0,articles INTEGER DEFAULT 0,
      avg_views REAL DEFAULT 0,avg_engagement REAL DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS title_tests(
      id INTEGER PRIMARY KEY,article_id INTEGER,candidate TEXT NOT NULL,score REAL NOT NULL,
      chosen INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(article_id) REFERENCES articles(id))''')
    if version < 2:
        c.execute("CREATE INDEX IF NOT EXISTS idx_topics_status_score ON topics(status, score DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_metrics_article ON metrics(article_id)")
        c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('version',?)", (str(SCHEMA_VERSION),))
    c.commit()

def add_topic(title, link='', source='', summary='', score=0):
    c=connect(); cur=c.execute('INSERT OR IGNORE INTO topics(title,link,source,summary,score) VALUES(?,?,?,?,?)',(title,link,source,summary,score)); c.commit(); tid=cur.lastrowid
    if not tid:
        row=c.execute('SELECT id FROM topics WHERE title=?',(title,)).fetchone(); tid=row[0] if row else None
    c.close(); return tid

def topic_seen(title):
    c=connect(); x=c.execute('SELECT 1 FROM topics WHERE title=?',(title,)).fetchone(); c.close(); return x is not None

def add_article(topic_id,title,path,ok,notes,category='',image_path='',status='queued'):
    c=connect(); cur=c.execute('INSERT INTO articles(topic_id,title,path,image_path,quality_ok,quality_notes,category,status) VALUES(?,?,?,?,?,?,?,?)',(topic_id,title,str(path),str(image_path),int(ok),notes,category,status)); c.commit(); aid=cur.lastrowid; c.close(); return aid

def add_title_candidates(article_id, candidates, chosen):
    c=connect()
    for item in candidates:
        c.execute('INSERT INTO title_tests(article_id,candidate,score,chosen) VALUES(?,?,?,?)',(article_id,item['title'],float(item['score']),int(item['title']==chosen)))
    c.commit(); c.close()

def list_recent(limit=10):
    c=connect(); rows=c.execute('SELECT id,title,path,quality_ok,category,status,created_at FROM articles ORDER BY id DESC LIMIT ?',(limit,)).fetchall(); c.close(); return rows

def add_metric(article_id,views=0,likes=0,comments=0,shares=0,source='manual'):
    c=connect(); c.execute('INSERT INTO metrics(article_id,views,likes,comments,shares,source) VALUES(?,?,?,?,?,?)',(article_id,views,likes,comments,shares,source)); c.commit(); c.close()

def update_topic_status(topic_id,status):
    c=connect(); c.execute('UPDATE topics SET status=? WHERE id=?',(status,topic_id)); c.commit(); c.close()

def update_article_status(article_id,status):
    c=connect(); c.execute('UPDATE articles SET status=? WHERE id=?',(status,article_id)); c.commit(); c.close()

def mark_article_published(article_id): update_article_status(article_id,'published')

def usage_today(day=None):
    day = day or datetime.now(timezone.utc).date().isoformat()
    c=connect(); row=c.execute('SELECT requests FROM ai_usage WHERE day=?',(day,)).fetchone(); c.close(); return int(row[0]) if row else 0

def reserve_ai_request(limit, day=None):
    day = day or datetime.now(timezone.utc).date().isoformat()
    c=connect()
    c.execute('BEGIN IMMEDIATE')
    row=c.execute('SELECT requests FROM ai_usage WHERE day=?',(day,)).fetchone()
    used=int(row[0]) if row else 0
    if used >= limit:
        c.rollback(); c.close(); return False
    if row: c.execute('UPDATE ai_usage SET requests=requests+1,updated_at=CURRENT_TIMESTAMP WHERE day=?',(day,))
    else: c.execute('INSERT INTO ai_usage(day,requests) VALUES(?,1)',(day,))
    c.commit(); c.close(); return True
