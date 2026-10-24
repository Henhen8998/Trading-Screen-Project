"""Small SQLite repository; each completed import is an atomic snapshot."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from tradeops.engine import ENGINE_VERSION, Result, read_csv, reconcile

SCHEMA = """
CREATE TABLE IF NOT EXISTS reconciliation_runs (
 id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, engine_version TEXT NOT NULL,
 tolerance_cents INTEGER NOT NULL CHECK(tolerance_cents >= 0),
 summary_json TEXT NOT NULL, source_metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS trades (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES reconciliation_runs(id),
 source TEXT NOT NULL CHECK(source IN ('internal','broker')),
 row_number INTEGER NOT NULL, trade_id TEXT NOT NULL,
 values_json TEXT NOT NULL, raw_values_json TEXT NOT NULL, errors_json TEXT NOT NULL,
 UNIQUE(run_id, source, row_number)
);
CREATE INDEX IF NOT EXISTS trades_lookup ON trades(run_id, trade_id);
CREATE TABLE IF NOT EXISTS exceptions (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES reconciliation_runs(id),
 trade_id TEXT NOT NULL, severity TEXT NOT NULL CHECK(severity IN ('High','Medium','Low')),
 status TEXT NOT NULL CHECK(status IN ('Open','Investigating','Resolved')),
 details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS exceptions_lookup ON exceptions(run_id, status, severity);
CREATE TABLE IF NOT EXISTS discrepancy_details (
 id INTEGER PRIMARY KEY, exception_id INTEGER NOT NULL REFERENCES exceptions(id),
 type TEXT NOT NULL, details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS discrepancy_lookup ON discrepancy_details(exception_id, type);
CREATE TABLE IF NOT EXISTS exception_status_history (
 id INTEGER PRIMARY KEY, exception_id INTEGER NOT NULL REFERENCES exceptions(id),
 old_status TEXT CHECK(old_status IN ('Open','Investigating','Resolved')),
 new_status TEXT NOT NULL CHECK(new_status IN ('Open','Investigating','Resolved')),
 note TEXT NOT NULL, changed_at TEXT NOT NULL,
 CHECK(new_status != 'Resolved' OR length(trim(note)) > 0)
);
CREATE INDEX IF NOT EXISTS history_lookup ON exception_status_history(exception_id, id);
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class Repository:
    def __init__(self, path='data/tradeops.sqlite3'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            # Additive upgrade: preserve databases created by the two-CSV MVP.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(reconciliation_runs)')}
            if 'source_metadata_json' not in columns:
                db.execute("ALTER TABLE reconciliation_runs ADD COLUMN source_metadata_json TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_csv(self, internal: bytes, broker: bytes, tolerance_cents=1):
        """Byte-identical input + policy + version reopens the previous run."""
        # Reconciliation also validates the tolerance, including on repeat imports.
        result = reconcile(read_csv(internal), read_csv(broker), tolerance_cents)
        fingerprint = hashlib.sha256(json.dumps({
            'internal': hashlib.sha256(internal).hexdigest(),
            'broker': hashlib.sha256(broker).hexdigest(),
            'tolerance_cents': tolerance_cents, 'engine': ENGINE_VERSION,
        }, sort_keys=True).encode()).hexdigest()
        return self.save(result, fingerprint, {'internal_source': 'legacy_csv', 'broker_sha256': hashlib.sha256(broker).hexdigest()})

    def import_internal_snapshot(self, store, snapshot_id, broker: bytes, tolerance_cents=1):
        """Query internal trades directly; only the broker input is a CSV."""
        internal, source = store.load_snapshot(snapshot_id)
        result = reconcile(internal, read_csv(broker), tolerance_cents)
        broker_hash = hashlib.sha256(broker).hexdigest()
        fingerprint = hashlib.sha256(json.dumps({
            'internal_source': 'database_snapshot', 'internal': source['fingerprint'],
            'broker': broker_hash, 'tolerance_cents': tolerance_cents,
            'engine': ENGINE_VERSION,
        }, sort_keys=True).encode()).hexdigest()
        metadata = {'internal_source': 'database_snapshot', 'internal_snapshot': source,
                    'broker_sha256': broker_hash}
        return self.save(result, fingerprint, metadata)

    def save(self, result: Result, fingerprint: str, source_metadata=None):
        with self.connect() as db:
            # Serialize competing imports before checking the unique fingerprint.
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM reconciliation_runs WHERE fingerprint=?', (fingerprint,)).fetchone()
            if existing:
                return existing['id'], False
            run_id = db.execute(
                'INSERT INTO reconciliation_runs(fingerprint,created_at,engine_version,tolerance_cents,summary_json,source_metadata_json) VALUES(?,?,?,?,?,?)',
                (fingerprint, utc_now(), ENGINE_VERSION, result.tolerance_cents, json.dumps(result.summary), json.dumps(source_metadata or {}))).lastrowid
            db.executemany('INSERT INTO trades(run_id,source,row_number,trade_id,values_json,raw_values_json,errors_json) VALUES(?,?,?,?,?,?,?)',
                           [(run_id, r['source'], r['row_number'], r['trade_id'], json.dumps(r['values']), json.dumps(r['raw_values']), json.dumps(r['errors'])) for r in result.rows])
            for item in result.exceptions:
                identifier = db.execute('INSERT INTO exceptions(run_id,trade_id,severity,status,details_json) VALUES(?,?,?,?,?)',
                                        (run_id, item['trade_id'], item['severity'], 'Open', json.dumps(item))).lastrowid
                db.executemany('INSERT INTO discrepancy_details(exception_id,type,details_json) VALUES(?,?,?)',
                               [(identifier, d['type'], json.dumps(d)) for d in item['discrepancies']])
                db.execute('INSERT INTO exception_status_history(exception_id,old_status,new_status,note,changed_at) VALUES(?,?,?,?,?)',
                           (identifier, None, 'Open', 'Created by reconciliation', utc_now()))
        return run_id, True

    def runs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM reconciliation_runs ORDER BY id DESC')]

    def exceptions(self, run_id):
        with self.connect() as db:
            return [dict(r) | {'details': json.loads(r['details_json'])} for r in db.execute('SELECT * FROM exceptions WHERE run_id=? ORDER BY id', (run_id,))]

    def history(self, exception_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM exception_status_history WHERE exception_id=? ORDER BY id', (exception_id,))]

    def update_status(self, exception_id, status, note):
        if status not in {'Open', 'Investigating', 'Resolved'}:
            raise ValueError('Unknown status')
        note = note.strip()
        if status == 'Resolved' and not note:
            raise ValueError('A resolution note is required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT status FROM exceptions WHERE id=?', (exception_id,)).fetchone()
            if not old:
                raise ValueError('Exception not found')
            if old['status'] == status:
                raise ValueError('Choose a different status')
            db.execute('UPDATE exceptions SET status=? WHERE id=?', (status, exception_id))
            db.execute('INSERT INTO exception_status_history(exception_id,old_status,new_status,note,changed_at) VALUES(?,?,?,?,?)',
                       (exception_id, old['status'], status, note, utc_now()))
