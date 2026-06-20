from __future__ import annotations

import sqlite3

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_fresh_db_boots(isolated_runtime):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            body = (await client.get("/api/health")).json()
    assert body["status"] == "ok"
    assert isolated_runtime["db_path"].exists()


async def test_legacy_db_without_image_metadata_columns_upgrades(isolated_runtime):
    _create_legacy_db(isolated_runtime["db_path"])
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/images")
    assert response.status_code == 200
    assert response.json()[0]["favorite"] is False
    with sqlite3.connect(isolated_runtime["db_path"]) as conn:
        column_rows = list(conn.execute("PRAGMA table_info(images)"))
        columns = {row[1] for row in column_rows}
        job_id = next(row for row in column_rows if row[1] == "job_id")
        image_foreign_keys = list(conn.execute("PRAGMA foreign_key_list(images)"))
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert {"family", "favorite", "tags"} <= columns
    assert job_id[3] == 0  # nullable: recovered images have no queue row
    assert not any(row[3] == "job_id" for row in image_foreign_keys)
    assert version == "0004_detach_history_from_queue"


def _create_legacy_db(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE jobs (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                type VARCHAR(16) NOT NULL,
                status VARCHAR(16) NOT NULL,
                priority INTEGER NOT NULL,
                model_id VARCHAR(128) NOT NULL,
                params JSON NOT NULL,
                progress FLOAT NOT NULL,
                result JSON,
                error TEXT,
                created_at DATETIME NOT NULL,
                started_at DATETIME,
                finished_at DATETIME
            );
            CREATE INDEX ix_jobs_status ON jobs (status);
            CREATE INDEX ix_jobs_priority ON jobs (priority);
            CREATE INDEX ix_jobs_type ON jobs (type);
            CREATE INDEX ix_jobs_created_at ON jobs (created_at);

            CREATE TABLE images (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                job_id VARCHAR(32) NOT NULL,
                path VARCHAR(512) NOT NULL,
                thumb_path VARCHAR(512),
                seed INTEGER,
                width INTEGER,
                height INTEGER,
                params JSON NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
            );
            CREATE INDEX ix_images_job_id ON images (job_id);
            CREATE INDEX ix_images_created_at ON images (created_at);

            INSERT INTO jobs (
                id, type, status, priority, model_id, params, progress, result, error,
                created_at, started_at, finished_at
            ) VALUES (
                'job1', 'image', 'done', 0, 'legacy-model', '{}', 1.0, '{}', NULL,
                '2026-01-01 00:00:00.000000', NULL, '2026-01-01 00:00:01.000000'
            );
            INSERT INTO images (
                id, job_id, path, thumb_path, seed, width, height, params, created_at
            ) VALUES (
                'img1', 'job1', '/missing.png', NULL, 123, 512, 512,
                '{"family":"sdxl","model":"legacy"}', '2026-01-01 00:00:01.000000'
            );
            """
        )
