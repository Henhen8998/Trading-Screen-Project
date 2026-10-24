"""Single-trade interview examples use the same database-backed engine."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tradeops.database import Repository
from tradeops.internal_store import InternalTradeStore
from tradeops.manual import run_single_trade


@pytest.fixture
def trade():
    return {'trade_id': 'WALK001', 'symbol': 'ALFA_SIM', 'side': 'BUY', 'quantity': '100',
            'price': '10.00', 'trade_date': '2026-01-05', 'settlement_date': '2026-01-06',
            'currency': 'USD', 'broker': 'Fictional North'}


def test_manual_match_uses_database_source(tmp_path, trade):
    identifier, created = run_single_trade(trade, trade, directory=tmp_path)
    repository = Repository(tmp_path / 'results.sqlite3')
    assert created and not repository.exceptions(identifier)
    assert json.loads(repository.runs()[0]['summary_json'])['matched_records'] == 1
    assert json.loads(repository.runs()[0]['source_metadata_json'])['internal_source'] == 'database_snapshot'
    store = InternalTradeStore(tmp_path / 'internal.sqlite3')
    assert store.load_snapshot(store.snapshots()[0]['id'])[0].iloc[0]['trade_id'] == 'WALK001'


def test_manual_quantity_and_repeat_preserve_history(tmp_path, trade):
    broker = trade | {'quantity': '110'}
    identifier, _ = run_single_trade(trade, broker, directory=tmp_path)
    repository = Repository(tmp_path / 'results.sqlite3')
    item = repository.exceptions(identifier)[0]
    assert item['details']['quantity_difference'] == -10
    assert item['details']['indicative_notional_cents'] == 10000
    repository.update_status(item['id'], 'Resolved', 'Interview example reviewed')
    assert run_single_trade(trade, broker, directory=tmp_path) == (identifier, False)
    assert repository.exceptions(identifier)[0]['status'] == 'Resolved'
    assert len(repository.history(item['id'])) == 2


@pytest.mark.parametrize('price,exceptions', [('10.01', 0), ('10.02', 1)])
def test_manual_tolerance(tmp_path, trade, price, exceptions):
    identifier, _ = run_single_trade(trade, trade | {'price': price}, directory=tmp_path)
    assert len(Repository(tmp_path / 'results.sqlite3').exceptions(identifier)) == exceptions


@pytest.mark.parametrize('missing', ['internal', 'broker'])
def test_manual_missing_record(tmp_path, trade, missing):
    identifier, _ = run_single_trade(None if missing == 'internal' else trade,
                                      None if missing == 'broker' else trade, directory=tmp_path)
    item = Repository(tmp_path / 'results.sqlite3').exceptions(identifier)[0]
    assert item['details']['discrepancies'][0]['type'] == f'MISSING_{missing.upper()}'


def test_manual_different_ids_and_invalid_input(tmp_path, trade):
    identifier, _ = run_single_trade(trade, trade | {'trade_id': 'OTHER'}, directory=tmp_path)
    repository = Repository(tmp_path / 'results.sqlite3')
    assert len(repository.exceptions(identifier)) == 2
    identifier, _ = run_single_trade(trade | {'quantity': 'bad'}, trade, directory=tmp_path)
    assert repository.exceptions(identifier)[0]['details']['discrepancies'][0]['type'] == 'INVALID_INPUT'
    with pytest.raises(ValueError, match='at least one'):
        run_single_trade(None, None, directory=tmp_path)
    with pytest.raises(ValueError, match='required fields'):
        run_single_trade({'trade_id': 'X'}, trade, directory=tmp_path)


def test_manual_dashboard_match_break_and_resolve(tmp_path, monkeypatch):
    app_path = Path(__file__).resolve().parents[1] / 'app.py'
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(app_path), default_timeout=40).run()
    app.sidebar.radio[0].set_value('Single-trade walkthrough').run()
    assert not app.exception
    assert not app.get('file_uploader')
    next(b for b in app.button if b.label == 'Reconcile this trade').click().run()
    assert not app.exception
    assert [m.value for m in app.metric] == ['1', '0', '0']
    next(w for w in app.text_input if w.key == 'manual_broker_quantity').input('110')
    next(b for b in app.button if b.label == 'Reconcile this trade').click().run()
    assert not app.exception
    assert [m.value for m in app.metric] == ['0', '1', '1']
    next(w for w in app.selectbox if w.label == 'New status').select('Resolved')
    next(b for b in app.button if b.label == 'Save walkthrough status').click().run()
    assert any('resolution note' in error.value for error in app.error)
    app.text_area[0].input('Verified the single-trade interview example')
    next(b for b in app.button if b.label == 'Save walkthrough status').click().run()
    assert not app.exception
    repository = Repository(tmp_path / 'data' / 'manual_demo' / 'results.sqlite3')
    assert repository.exceptions(2)[0]['status'] == 'Resolved'
    assert Repository(tmp_path / 'data' / 'tradeops.sqlite3').runs() == []
    # Two different IDs illustrate one missing record on each side.
    next(w for w in app.text_input if w.key == 'manual_broker_trade_id').input('OTHER')
    next(b for b in app.button if b.label == 'Reconcile this trade').click().run()
    assert not app.exception
    assert [m.value for m in app.metric] == ['0', '2', '2']
