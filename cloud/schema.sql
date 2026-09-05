CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY,
  headline TEXT NOT NULL,
  category TEXT,
  article_markdown TEXT NOT NULL,
  source_urls_json TEXT NOT NULL DEFAULT '[]',
  fact_check_json TEXT NOT NULL DEFAULT '[]',
  image_url TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  quality_ok INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);

CREATE TABLE IF NOT EXISTS metrics (
  article_id INTEGER PRIMARY KEY,
  views INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  shares INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_usage (
  day TEXT PRIMARY KEY,
  requests INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

-- Generic shared resource counters. Keep OpenRouter request telemetry in
-- ai_usage unchanged; Workers AI neurons use a separate resource row so the
-- two independent daily budgets cannot interfere with each other.
CREATE TABLE IF NOT EXISTS resource_usage (
  day TEXT NOT NULL,
  resource TEXT NOT NULL,
  used REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(day, resource)
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
