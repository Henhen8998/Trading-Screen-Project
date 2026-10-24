"""Simulated internal trade source, separate from reconciliation results.

The seeder models upstream trade capture. Reconciliation only reads immutable
snapshots through a read-only SQLite connection; it never edits source trades.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd

from tradeops.database import utc_now
from tradeops.engine import FIELDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS internal_snapshots (
 id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL, seed INTEGER NOT NULL, row_count INTEGER NOT NULL,
 CHECK(row_count >= 0)
);
CREATE TABLE IF NOT EXISTS internal_trade_records (
 id INTEGER PRIMARY KEY,
 snapshot_id INTEGER NOT NULL REFERENCES internal_snapshots(id),
 source_row INTEGER NOT NULL,
 trade_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
 quantity TEXT NOT NULL, price TEXT NOT NULL, trade_date TEXT NOT NULL,
 settlement_date TEXT NOT NULL, currency TEXT NOT NULL, broker TEXT NOT NULL,
 UNIQUE(snapshot_id, source_row)
);
CREATE INDEX IF NOT EXISTS internal_id_lookup ON internal_trade_records(snapshot_id, trade_id);
CREATE INDEX IF NOT EXISTS internal_date_lookup ON internal_trade_records(snapshot_id, trade_date);
"""


class InternalTradeStore:
    """Append-only simulated source snapshots; duplicate trade IDs are evidence.

    Source columns stay text so malformed records can reach engine validation.
    This models a source extract/landing table, not a production booking ledger.
    """

    def __init__(self, path='data/internal_trades.sqlite3'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self, readonly=False):
        db = (sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
              if readonly else sqlite3.connect(self.path))
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed_snapshot(self, frame: pd.DataFrame, seed: int):
        """Simulate upstream capture without replacing earlier source snapshots."""
        if set(frame.columns) != set(FIELDS):
            raise ValueError('Internal snapshot must contain exactly the required trade fields')
        records = frame[FIELDS].fillna('').astype(str).to_dict('records')
        fingerprint = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        columns = ','.join(FIELDS)  # Identifiers are application constants, never user text.
        placeholders = ','.join('?' for _ in range(len(FIELDS) + 2))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM internal_snapshots WHERE fingerprint=?', (fingerprint,)).fetchone()
            if existing:
                return existing['id']
            snapshot_id = db.execute('INSERT INTO internal_snapshots(fingerprint,created_at,seed,row_count) VALUES(?,?,?,?)',
                                     (fingerprint, utc_now(), seed, len(records))).lastrowid
            db.executemany(f'INSERT INTO internal_trade_records(snapshot_id,source_row,{columns}) VALUES({placeholders})',
                           [(snapshot_id, index, *(r[f] for f in FIELDS)) for index, r in enumerate(records, start=2)])
        return snapshot_id

    def snapshots(self):
        with self.connect(readonly=True) as db:
            return [dict(r) for r in db.execute('SELECT * FROM internal_snapshots ORDER BY id DESC')]

    def load_snapshot(self, snapshot_id):
        """Read one complete population, never filter to broker-provided IDs."""
        columns = ','.join(FIELDS)
        with self.connect(readonly=True) as db:
            db.execute('BEGIN')
            snapshot = db.execute('SELECT * FROM internal_snapshots WHERE id=?', (snapshot_id,)).fetchone()
            if not snapshot:
                raise ValueError('Internal snapshot not found; load demo data first')
            rows = db.execute(f'SELECT {columns} FROM internal_trade_records WHERE snapshot_id=? ORDER BY source_row', (snapshot_id,)).fetchall()
        frame = pd.DataFrame([dict(r) for r in rows], columns=FIELDS)
        if len(frame) != snapshot['row_count']:
            raise ValueError('Internal snapshot row count differs from recorded metadata')
        actual_hash = hashlib.sha256(json.dumps(frame.to_dict('records'), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if actual_hash != snapshot['fingerprint']:
            raise ValueError('Internal snapshot contents changed; create a new snapshot instead of editing history')
        metadata = dict(snapshot) | {'database': str(self.path.resolve()), 'source_type': 'internal_database_snapshot'}
        return frame, metadata

    def seed_sample(self, seed=42):
        from tradeops.synthetic import generate
        internal, broker, truth = generate(seed)
        snapshot_id = self.seed_snapshot(internal, seed)
        return snapshot_id, broker, truth


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--database', default='data/internal_trades.sqlite3')
    parser.add_argument('--output', default='data')
    args = parser.parse_args()
    store = InternalTradeStore(args.database)
    snapshot_id, broker, truth = store.seed_sample(args.seed)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    broker.to_csv(output / 'broker_trades.csv', index=False)
    truth.to_csv(output / 'ground_truth.csv', index=False)
    print(f'Internal database snapshot {snapshot_id} ready; broker CSV and ground truth written to {output}')
