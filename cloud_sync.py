import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import DB_PATH, OUTBOX_DIR
from db import connect

API = (
    "https://api.cloudflare.com/client/v4/accounts/"
    "{account}/d1/database/{db}/query"
)


def enabled():
    return all(
        os.getenv(k, "").strip()
        for k in (
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_D1_DATABASE_ID",
        )
    )


def query(sql, params=None):
    if not enabled():
        return None

    url = API.format(
        account=os.environ["CLOUDFLARE_ACCOUNT_ID"],
        db=os.environ["CLOUDFLARE_D1_DATABASE_ID"],
    )

    response = requests.post(
        url,
        headers={
            "Authorization": (
                f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"
            ),
            "Content-Type": "application/json",
        },
        json={
            "sql": sql,
            "params": params or [],
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("success"):
        raise RuntimeError(str(data))

    return data["result"][0]


def init_schema(schema_path=None):
    schema_path = Path(
        schema_path
        or Path(__file__).parent / "cloud" / "schema.sql"
    )

    sql = schema_path.read_text(
        encoding="utf-8"
    )

    return query(sql)


def hydrate_local():
    if not enabled():
        return 0

    # Важно:
    # db.connect() автоматически создаёт и мигрирует
    # локальную SQLite-схему перед синхронизацией.
    c = connect()

    result = query(
        """
        SELECT
            id,
            headline,
            category,
            status,
            quality_ok,
            created_at
        FROM articles
        ORDER BY id
        """
    ) or {}

    rows = result.get("results", [])

    for row in rows:
        c.execute(
            """
            INSERT OR IGNORE INTO articles(
                id,
                topic_id,
                title,
                path,
                image_path,
                quality_ok,
                quality_notes,
                category,
                status,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            [
                row.get("id"),
                None,
                row.get("headline", ""),
                "",
                "",
                int(row.get("quality_ok", 0)),
                "",
                row.get("category", ""),
                row.get("status", "queued"),
                row.get("created_at"),
            ],
        )

        c.execute(
            """
            UPDATE articles
            SET
                title=?,
                category=?,
                status=?,
                quality_ok=?,
                created_at=?
            WHERE id=?
            """,
            [
                row.get("headline", ""),
                row.get("category", ""),
                row.get("status", "queued"),
                int(row.get("quality_ok", 0)),
                row.get("created_at"),
                row.get("id"),
            ],
        )

    result = query(
        """
        SELECT
            article_id,
            views,
            likes,
            comments,
            shares,
            updated_at
        FROM metrics
        """
    ) or {}

    for row in result.get("results", []):
        c.execute(
            """
            INSERT INTO metrics(
                article_id,
                views,
                likes,
                comments,
                shares,
                source,
                created_at
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            [
                row.get("article_id"),
                row.get("views", 0),
                row.get("likes", 0),
                row.get("comments", 0),
                row.get("shares", 0),
                "cloud",
                row.get("updated_at"),
            ],
        )

    c.commit()
    c.close()

    return len(rows)


def sync_local():
    if not enabled():
        return 0

    # Здесь тоже используем db.connect(),
    # чтобы таблицы гарантированно существовали.
    c = connect()

    articles = c.execute(
        """
        SELECT
            id,
            title,
            category,
            quality_ok,
            status,
            created_at
        FROM articles
        """
    ).fetchall()

    synced = 0

    for (
        article_id,
        title,
        category,
        quality_ok,
        status,
        created_at,
    ) in articles:

        manifest = None

        for path in OUTBOX_DIR.glob("*.json"):
            try:
                item = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )

                if item.get("headline") == title:
                    manifest = item
                    break

            except Exception:
                pass

        if not manifest:
            continue

        now = (
            created_at
            or datetime.now(
                timezone.utc
            ).isoformat()
        )

        query(
            """
            INSERT INTO articles(
                id,
                headline,
                category,
                article_markdown,
                source_urls_json,
                fact_check_json,
                image_url,
                status,
                quality_ok,
                created_at,
                updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)

            ON CONFLICT(id)
            DO UPDATE SET
                headline=excluded.headline,
                category=excluded.category,
                article_markdown=excluded.article_markdown,
                source_urls_json=excluded.source_urls_json,
                fact_check_json=excluded.fact_check_json,
                image_url=excluded.image_url,
                status=excluded.status,
                quality_ok=excluded.quality_ok,
                updated_at=excluded.updated_at
            """,
            [
                article_id,
                title,
                category or "",
                manifest.get(
                    "article_markdown",
                    "",
                ),
                json.dumps(
                    manifest.get(
                        "source_urls",
                        [],
                    ),
                    ensure_ascii=False,
                ),
                json.dumps(
                    manifest.get(
                        "fact_check",
                        [],
                    ),
                    ensure_ascii=False,
                ),
                manifest.get(
                    "image_url"
                ),
                status,
                int(quality_ok),
                now,
                now,
            ],
        )

        synced += 1

    # Сохраняем обученную стратегию категорий
    # для Telegram Worker.
    try:
        rows = c.execute(
            """
            SELECT
                category,
                weight,
                articles,
                avg_views,
                avg_engagement
            FROM strategy
            """
        ).fetchall()

        strategy = {
            "categories": {
                row[0]: {
                    "weight": row[1],
                    "articles": row[2],
                    "avg_views": row[3],
                    "avg_engagement": row[4],
                }
                for row in rows
            },
            "updated_articles": sum(
                row[2]
                for row in rows
            ),
        }

        query(
            """
            INSERT INTO settings(
                key,
                value,
                updated_at
            )
            VALUES(
                'strategy',
                ?,
                ?
            )

            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            [
                json.dumps(
                    strategy,
                    ensure_ascii=False,
                ),
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ],
        )

    except Exception:
        pass

    c.close()

    return synced


if __name__ == "__main__":
    print(
        "Cloud hydrate:",
        hydrate_local()
        if enabled()
        else "disabled",
    )

    print(
        "Cloud sync:",
        sync_local()
        if enabled()
        else "disabled",
    )
