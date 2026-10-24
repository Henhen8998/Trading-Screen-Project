"""Database-source integration, provenance, and preservation of the old MVP."""
import json
import sqlite3

import pandas as pd
import pytest

from tradeops.database import Repository
from tradeops.engine import FIELDS
from tradeops.internal_store import InternalTradeStore
from tradeops.reporting import report_tables
from tradeops.synthetic import generate


@pytest.fixture
def source(tmp_path):
    store = InternalTradeStore(tmp_path / 'internal.sqlite3')
    internal, broker, truth = generate()
    snapshot_id = store.seed_snapshot(internal, seed=42)
    repository = Repository(tmp_path / 'results.sqlite3')
    return store, snapshot_id, internal, broker, truth, repository


def test_database_source_matches_ground_truth(source):
    store, snapshot_id, internal, broker, truth, repository = source
    run_id, created = repository.import_internal_snapshot(store, snapshot_id, broker.to_csv(index=False).encode())
    assert created
    detected = {(e['trade_id'], d['type']) for e in repository.exceptions(run_id) for d in e['details']['discrepancies']}
    assert detected == set(zip(truth['trade_id'], truth['type']))
    assert json.loads(repository.runs()[0]['summary_json'])['matched_records'] == 935
    actual, metadata = store.load_snapshot(snapshot_id)
    pd.testing.assert_frame_equal(actual, internal)
    assert metadata['database'] == str(store.path.resolve())


def test_source_snapshot_idempotency_and_history(source):
    store, snapshot_id, internal, broker, _, repository = source
    assert store.seed_snapshot(internal, seed=42) == snapshot_id
    assert len(store.snapshots()) == 1
    payload = broker.to_csv(index=False).encode()
    run_id, _ = repository.import_internal_snapshot(store, snapshot_id, payload)
    identifier = repository.exceptions(run_id)[0]['id']
    repository.update_status(identifier, 'Resolved', 'Checked simulated source')
    assert repository.import_internal_snapshot(store, snapshot_id, payload) == (run_id, False)
    assert repository.exceptions(run_id)[0]['status'] == 'Resolved'
    assert len(repository.history(identifier)) == 2
    new_id, _, _ = store.seed_sample(seed=43)
    assert new_id != snapshot_id
    assert len(store.snapshots()) == 2
    pd.testing.assert_frame_equal(store.load_snapshot(snapshot_id)[0], internal)
    new_run, created = repository.import_internal_snapshot(store, snapshot_id, payload, tolerance_cents=30)
    assert created and new_run != run_id


def test_database_population_not_filtered_to_broker_ids(source):
    store, snapshot_id, _, broker, _, repository = source
    broker = broker[broker['trade_id'] != 'SIM000100'].copy()
    extra = broker.iloc[100].to_dict() | {'trade_id': 'BROKER_ONLY'}
    broker = pd.concat([broker, pd.DataFrame([extra])], ignore_index=True)
    run_id, _ = repository.import_internal_snapshot(store, snapshot_id, broker.to_csv(index=False).encode())
    detected = {(e['trade_id'], d['type']) for e in repository.exceptions(run_id) for d in e['details']['discrepancies']}
    assert ('SIM000100', 'MISSING_BROKER') in detected
    assert ('BROKER_ONLY', 'MISSING_INTERNAL') in detected


def test_internal_invalid_rows_are_validated_and_retained(source):
    store, _, internal, broker, _, repository = source
    internal.loc[internal['trade_id'] == 'SIM000100', 'quantity'] = 'invalid'
    snapshot_id = store.seed_snapshot(internal, seed=42)
    run_id, _ = repository.import_internal_snapshot(store, snapshot_id, broker.to_csv(index=False).encode())
    item = next(e for e in repository.exceptions(run_id) if e['trade_id'] == 'SIM000100')
    assert item['details']['discrepancies'][0]['type'] == 'INVALID_INPUT'
    assert item['details']['internal'][0]['quantity'] == 'invalid'


def test_source_read_connection_is_read_only(source):
    store = source[0]
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        with store.connect(readonly=True) as db:
            db.execute("UPDATE internal_trade_records SET quantity='1'")


@pytest.mark.parametrize('mutation', ["UPDATE internal_trade_records SET quantity='1' WHERE id=100",
                                    'DELETE FROM internal_trade_records WHERE id=100'])
def test_changed_snapshot_is_rejected(source, mutation):
    store, snapshot_id, _, broker, _, repository = source
    with store.connect() as db:
        db.execute(mutation)
    with pytest.raises(ValueError, match='snapshot'):
        repository.import_internal_snapshot(store, snapshot_id, broker.to_csv(index=False).encode())
    assert repository.runs() == []


def test_unknown_snapshot_and_empty_population(source):
    store, _, _, broker, _, repository = source
    with pytest.raises(ValueError, match='not found'):
        store.load_snapshot('1 OR 1=1')
    with pytest.raises(ValueError, match='not found'):
        repository.import_internal_snapshot(store, -1, broker.to_csv(index=False).encode())
    assert repository.runs() == []
    empty = pd.DataFrame(columns=FIELDS)
    snapshot_id = store.seed_snapshot(empty, seed=0)
    run_id, _ = repository.import_internal_snapshot(store, snapshot_id, empty.to_csv(index=False).encode())
    assert json.loads(repository.runs()[0]['summary_json'])['match_rate'] is None
    assert not repository.exceptions(run_id)


def test_provenance_in_database_and_reports(source):
    store, snapshot_id, _, broker, _, repository = source
    run_id, _ = repository.import_internal_snapshot(store, snapshot_id, broker.to_csv(index=False).encode())
    metadata = json.loads(repository.runs()[0]['source_metadata_json'])
    assert metadata['internal_source'] == 'database_snapshot'
    assert metadata['internal_snapshot']['id'] == snapshot_id
    summary = report_tables(repository, run_id)['Summary']
    values = dict(zip(summary['metric'], summary['value']))
    assert values['internal_source'] == 'database_snapshot'
    assert values['internal_snapshot_sha256'] == metadata['internal_snapshot']['fingerprint']
    assert values['broker_file_sha256'] == metadata['broker_sha256']


def test_existing_database_upgrade_preserves_runs(source):
    _, _, internal, broker, _, repository = source
    payloads = internal.to_csv(index=False).encode(), broker.to_csv(index=False).encode()
    run_id, _ = repository.import_csv(*payloads)
    identifier = repository.exceptions(run_id)[0]['id']
    repository.update_status(identifier, 'Resolved', 'Historical resolution')
    # Reproduce the original schema, which had no source metadata column.
    with repository.connect() as db:
        db.execute('ALTER TABLE reconciliation_runs DROP COLUMN source_metadata_json')
    upgraded = Repository(repository.path)
    assert upgraded.import_csv(*payloads) == (run_id, False)
    assert upgraded.exceptions(run_id)[0]['status'] == 'Resolved'
    assert len(upgraded.history(identifier)) == 2
    assert json.loads(upgraded.runs()[0]['source_metadata_json']) == {}
