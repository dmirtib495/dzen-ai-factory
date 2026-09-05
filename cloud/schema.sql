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

CREATE TABLE IF NOT EXISTS resource_usage (
  day TEXT NOT NULL,
  resource TEXT NOT NULL,
  used REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(day, resource)
);

CREATE TABLE IF NOT EXISTS image_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id INTEGER NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'generating',
  source_run_id TEXT NOT NULL,
  artifact_name TEXT NOT NULL,
  candidate_json TEXT NOT NULL DEFAULT '[]',
  telegram_message_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(article_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_image_batches_article ON image_batches(article_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_image_batches_status ON image_batches(status);

CREATE TABLE IF NOT EXISTS article_packages (
  article_id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  package_day TEXT NOT NULL,
  source_run_id TEXT NOT NULL,
  artifact_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_article_packages_day ON article_packages(package_day, status);

CREATE TABLE IF NOT EXISTS daily_packages (
  day TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  telegram_message_id INTEGER,
  article_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
