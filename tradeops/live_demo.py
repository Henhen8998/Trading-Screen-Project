"""A staged, assertion-backed demonstration using an isolated SQLite database."""
from pathlib import Path

from tradeops.database import Repository
from tradeops.engine import reconcile
from tradeops.internal_store import InternalTradeStore
from tradeops.reporting import csv_bytes, excel_bytes, report_tables
from tradeops.synthetic import generate

STEPS = [
    'Seed 1,000 internal database rows and prepare broker confirmations',
    'Query internal database, reconcile, and save an atomic run',
    'Compare every finding with ground truth',
    'Inspect a quantity discrepancy',
    'Move the exception to Investigating',
    'Verify resolution without a note is rejected',
    'Resolve with a documented note',
    'Reimport identical files and verify history is preserved',
    'Generate CSV and Excel reports',
]


class LiveDemo:
    """Each advance performs one real operation and verifies its result."""

    def __init__(self, database_path):
        self.repository = Repository(database_path)
        self.internal_store = InternalTradeStore(Path(database_path).parent / 'internal_trades.sqlite3')
        self.events = []
        self.next_step = 0
        self.run_id = None
        self.exception_id = None
        self.result = None
        self.csv = None
        self.workbook = None

    @property
    def done(self):
        return self.next_step == len(STEPS)

    def advance(self):
        if self.done:
            return
        step = self.next_step
        if step == 0:
            self.internal, self.broker, self.truth = generate(seed=42)
            self.snapshot_id = self.internal_store.seed_snapshot(self.internal, seed=42)
            self.broker_bytes = self.broker.to_csv(index=False).encode()
            assert len(self.internal) == len(self.broker) == 1000
            message = 'Seeded 1,000 internal rows in a separate source database and prepared 1,000 broker CSV rows. No internal CSV upload.'
        elif step == 1:
            internal, _ = self.internal_store.load_snapshot(self.snapshot_id)
            self.result = reconcile(internal, self.broker)
            self.run_id, created = self.repository.import_internal_snapshot(self.internal_store, self.snapshot_id, self.broker_bytes)
            assert created and self.result.matched == 935
            assert len(self.result.exceptions) == 65
            message = 'Saved 2,000 source rows: 935 matched IDs, 65 exception records, 70 individual findings.'
        elif step == 2:
            detected = {(e['trade_id'], d['type']) for e in self.result.exceptions for d in e['discrepancies']}
            expected = set(zip(self.truth['trade_id'], self.truth['type']))
            assert detected == expected
            message = f'All {len(expected)} expected (trade ID, type) findings detected; no unexpected findings in this fixture.'
        elif step == 3:
            selected = next(e for e in self.repository.exceptions(self.run_id)
                            if any(d['type'] == 'QUANTITY' for d in e['details']['discrepancies']))
            self.exception_id = selected['id']
            assert selected['details']['quantity_difference'] == -100
            message = f"{selected['trade_id']}: internal minus broker quantity = -100 shares. Both source values are shown below."
        elif step == 4:
            self.repository.update_status(self.exception_id, 'Investigating', 'Live demo: checking the simulated broker confirmation.')
            assert self.repository.history(self.exception_id)[-1]['new_status'] == 'Investigating'
            message = 'Open → Investigating. A timestamped history entry was saved.'
        elif step == 5:
            previous = self.repository.history(self.exception_id)
            try:
                self.repository.update_status(self.exception_id, 'Resolved', '')
            except ValueError as exc:
                assert 'resolution note' in str(exc)
            else:
                raise AssertionError('Resolution without a note was incorrectly accepted')
            assert self.repository.history(self.exception_id) == previous
            message = 'Expected rejection: a resolution note is required. Status and history remained unchanged.'
        elif step == 6:
            self.repository.update_status(self.exception_id, 'Resolved', 'Live demo: reviewed the fictional quantity break; no real source correction was performed.')
            assert self.repository.history(self.exception_id)[-1]['new_status'] == 'Resolved'
            message = 'Investigating → Resolved with a note. The original reconciliation result is unchanged.'
        elif step == 7:
            repeat_id, created = self.repository.import_internal_snapshot(self.internal_store, self.snapshot_id, self.broker_bytes)
            assert repeat_id == self.run_id and not created
            assert len(self.repository.runs()) == 1
            assert len(self.repository.history(self.exception_id)) == 3
            selected = next(e for e in self.repository.exceptions(self.run_id) if e['id'] == self.exception_id)
            assert selected['status'] == 'Resolved'
            message = 'Same run reopened; no duplicate run or source rows. Resolved status and all three history entries preserved.'
        else:
            tables = report_tables(self.repository, self.run_id)
            assert len(tables['Outstanding']) == 64
            self.csv = csv_bytes(tables['Exceptions'])
            self.workbook = excel_bytes(tables)
            assert self.workbook[:2] == b'PK'
            destination = Path(self.repository.path).parent
            (destination / 'exceptions.csv').write_bytes(self.csv)
            (destination / 'tradeops_live_test.xlsx').write_bytes(self.workbook)
            message = 'CSV and seven-sheet Excel reports generated. 64 exception records remain outstanding.'
        self.events.append({'step': step + 1, 'check': STEPS[step], 'result': 'PASS', 'detail': message})
        self.next_step += 1
