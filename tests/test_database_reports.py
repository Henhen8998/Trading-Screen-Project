import json
import sqlite3
from zipfile import ZipFile
from io import BytesIO

import pandas as pd
import pytest

from tradeops.database import Repository
from tradeops.engine import reconcile
from tradeops.reporting import csv_bytes, excel_bytes, report_tables
from tradeops.synthetic import generate


@pytest.fixture
def imported(tmp_path):
    repository = Repository(tmp_path / 'test.sqlite3')
    a, b, _ = generate()
    payloads = a.to_csv(index=False).encode(), b.to_csv(index=False).encode()
    run_id, created = repository.import_csv(*payloads)
    assert created
    return repository, run_id, payloads


def test_repeat_import_preserves_workflow(imported):
    repository, run_id, payloads = imported
    item = repository.exceptions(run_id)[0]
    repository.update_status(item['id'], 'Investigating', 'Checking confirmation')
    repository.update_status(item['id'], 'Resolved', 'Corrected in fictional source system')
    assert repository.import_csv(*payloads) == (run_id, False)
    assert len(repository.runs()) == 1
    assert repository.exceptions(run_id)[0]['status'] == 'Resolved'
    assert len(repository.history(item['id'])) == 3
    repository.update_status(item['id'], 'Open', 'Reopened for review')
    assert repository.history(item['id'])[-1]['old_status'] == 'Resolved'
    with repository.connect() as db:
        assert db.execute('SELECT count(*) FROM trades').fetchone()[0] == 2000


def test_policy_changes_make_new_run(imported):
    repository, run_id, payloads = imported
    new_id, created = repository.import_csv(*payloads, tolerance_cents=30)
    assert created and new_id != run_id
    assert len(repository.runs()) == 2


def test_status_validation(imported):
    repository, run_id, _ = imported
    identifier = repository.exceptions(run_id)[0]['id']
    for status, note in [('Resolved', '   '), ('Invalid', 'note'), ('Open', 'same state')]:
        with pytest.raises(ValueError):
            repository.update_status(identifier, status, note)
    with pytest.raises(ValueError):
        repository.update_status(-1, 'Investigating', 'test')
    assert len(repository.history(identifier)) == 1


def test_constraints_and_rollback(imported):
    repository, _, _ = imported
    with pytest.raises(sqlite3.IntegrityError):
        with repository.connect() as db:
            db.execute("INSERT INTO exceptions(run_id,trade_id,severity,status,details_json) VALUES(9999,'x','High','Open','{}')")
    a, b, _ = generate()
    result = reconcile(a, b)
    result.exceptions[0]['severity'] = 'invalid severity'
    with pytest.raises(sqlite3.IntegrityError):
        repository.save(result, 'must-rollback')
    assert len(repository.runs()) == 1
    with repository.connect() as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('SELECT count(*) FROM trades').fetchone()[0] == 2000


def test_invalid_import_does_not_write(imported):
    repository, _, payloads = imported
    with pytest.raises(ValueError):
        repository.import_csv(b'bad\n1\n', payloads[1])
    assert len(repository.runs()) == 1


def test_reports_counts_history_and_excel(imported):
    repository, run_id, _ = imported
    identifier = repository.exceptions(run_id)[0]['id']
    repository.update_status(identifier, 'Resolved', 'Reviewed')
    tables = report_tables(repository, run_id)
    summary = dict(zip(tables['Summary']['metric'], tables['Summary']['value']))
    assert summary['exception_records'] == 65
    assert summary['individual_discrepancies'] == 70
    assert summary['outstanding_exception_records'] == 64
    assert len(tables['Exceptions']) == 65
    assert len(tables['Discrepancies']) == 70
    assert len(tables['Status history']) == 66
    assert len(tables['Source rows']) == 2000
    assert 'indicative_notional_cents' in csv_bytes(tables['Exceptions']).decode('utf-8-sig')
    with ZipFile(BytesIO(excel_bytes(tables))) as workbook:
        assert len([n for n in workbook.namelist() if n.startswith('xl/worksheets/sheet')]) == 7
        assert b'Outstanding' in workbook.read('xl/workbook.xml')


def test_formula_escaping():
    content = csv_bytes(pd.DataFrame({'note': ['=1+1', ' @SUM(A1)', 'plain'], 'cents': [-100, 0, 100]})).decode('utf-8-sig')
    assert "'=1+1" in content
    assert "' @SUM(A1)" in content
    assert '-100' in content
    with ZipFile(BytesIO(excel_bytes({'Test': pd.DataFrame({'text': ['=1+1']})}))) as workbook:
        assert b'<f>' not in workbook.read('xl/worksheets/sheet1.xml')


def test_currency_totals_are_separate(tmp_path):
    repository = Repository(tmp_path / 'currencies.sqlite3')
    a, b, _ = generate()
    a.loc[0, 'currency'] = b.loc[0, 'currency'] = 'EUR'
    run_id, _ = repository.import_csv(a.to_csv(index=False).encode(), b.to_csv(index=False).encode())
    table = report_tables(repository, run_id)['Summary']
    metrics = dict(zip(table['metric'], table['value']))
    assert metrics['outstanding_indicative_notional_EUR_cents'] > 0
    assert metrics['outstanding_indicative_notional_USD_cents'] > 0
    assert 'outstanding_indicative_notional_cents' not in metrics
