-- Consolidated schema: all tables for log, ledger, librarian, and tasks

CREATE TABLE IF NOT EXISTS events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                REAL    NOT NULL,
    task_id           TEXT,
    category          TEXT    NOT NULL,
    message           TEXT    NOT NULL,
    level             TEXT    NOT NULL DEFAULT 'info',
    model             TEXT,
    provider          TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    elapsed_s         REAL,
    data              TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_task_id  ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_ts       ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_cat_task ON events(category, task_id);
CREATE INDEX IF NOT EXISTS idx_events_level    ON events(level);

CREATE TABLE IF NOT EXISTS tasks (
    task_id           TEXT    PRIMARY KEY,
    prompt            TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'queued',
    submitted_at      REAL    NOT NULL,
    started_at        REAL,
    finished_at       REAL,
    elapsed_s         REAL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    tokens_out        INTEGER,
    words_out         INTEGER,
    error             TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_submitted ON tasks(submitted_at);

CREATE TABLE IF NOT EXISTS stats (
    key        TEXT    PRIMARY KEY,
    value      INTEGER NOT NULL DEFAULT 0,
    updated_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS locks (
    resource    TEXT    PRIMARY KEY,
    held_by     TEXT    NOT NULL,
    acquired_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resource    TEXT    NOT NULL,
    agent_id    TEXT    NOT NULL,
    queued_at   REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS lib_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query      TEXT    NOT NULL,
    result     TEXT    NOT NULL,
    created_at REAL    NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS lib_entries_fts USING fts5(
    query, result,
    content='lib_entries', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS lib_vec_entries USING vec0(
    embedding float[768]
);

CREATE TRIGGER IF NOT EXISTS lib_entries_ai AFTER INSERT ON lib_entries BEGIN
    INSERT INTO lib_entries_fts(rowid, query, result)
    VALUES (new.id, new.query, new.result);
END;
