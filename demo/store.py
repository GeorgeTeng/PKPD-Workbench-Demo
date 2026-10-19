"""Append-only, source-bound demonstration notes. Never promotes workflow approval."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class ReviewStore:
    def __init__(self, state):
        Path(state).mkdir(parents=True, exist_ok=True)
        self.path = Path(state) / 'review_notes.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, created TEXT NOT NULL, body TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, record):
        row = dict(record, id=uuid4().hex, created_at=datetime.now(timezone.utc).isoformat(),
                   scope='DEMO_REVIEW_NOTE_ONLY', scientific_approval=False,
                   changes_workflow_permissions=False)
        with self.connect() as db:
            db.execute('INSERT INTO notes VALUES (?, ?, ?)',
                       (row['id'], row['created_at'], json.dumps(row, ensure_ascii=False)))
        return row

    def list(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM notes ORDER BY created DESC, id')]
