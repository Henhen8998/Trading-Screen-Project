"""Human-readable exports with formula-safe user text and exact cents."""
from collections import defaultdict
from io import BytesIO
import json

import pandas as pd


def safe_frame(frame):
    """Escape spreadsheet formula text without changing numeric columns."""
    result = frame.copy()
    for column in result.columns:
        if not pd.api.types.is_numeric_dtype(result[column].dtype):
            result[column] = result[column].map(
                lambda value: "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value)
    return result


def exception_frame(exceptions):
    columns = ['exception_id', 'trade_id', 'severity', 'status', 'types', 'quantity_difference',
               'price_difference_cents', 'indicative_notional_cents', 'currency', 'internal_values', 'broker_values']
    records = []
    for item in exceptions:
        d = item['details']
        records.append({'exception_id': item['id'], 'trade_id': item['trade_id'], 'severity': item['severity'],
                        'status': item['status'], 'types': ', '.join(x['type'] for x in d['discrepancies']),
                        **{k: d[k] for k in ['quantity_difference', 'price_difference_cents', 'indicative_notional_cents', 'currency']},
                        'internal_values': json.dumps(d['internal']), 'broker_values': json.dumps(d['broker'])})
    frame = pd.DataFrame(records, columns=columns)
    # Nullable integer columns prevent missing values from coercing money to float.
    for column in ['quantity_difference', 'price_difference_cents', 'indicative_notional_cents']:
        frame[column] = pd.array([r[column] for r in records], dtype='Int64')
    return frame


def report_tables(repository, run_id):
    run = next(r for r in repository.runs() if r['id'] == run_id)
    exceptions = repository.exceptions(run_id)
    summary = json.loads(run['summary_json']) | {'run_id': run_id, 'run_timestamp_utc': run['created_at'],
                                               'data_label': 'SIMULATED', 'price_tolerance_cents': run['tolerance_cents']}
    source = json.loads(run['source_metadata_json'])
    summary['internal_source'] = source.get('internal_source', 'legacy_csv')
    if 'internal_snapshot' in source:
        snapshot = source['internal_snapshot']
        summary.update({'internal_snapshot_id': snapshot['id'], 'internal_snapshot_timestamp_utc': snapshot['created_at'],
                        'internal_snapshot_sha256': snapshot['fingerprint'], 'internal_source_database': snapshot['database']})
    if 'broker_sha256' in source:
        summary['broker_file_sha256'] = source['broker_sha256']
    outstanding = [e for e in exceptions if e['status'] != 'Resolved']
    summary['outstanding_exception_records'] = len(outstanding)
    summary['outstanding_individual_discrepancies'] = sum(len(e['details']['discrepancies']) for e in outstanding)
    # Never sum different currencies; these are recorded-value differences, not losses.
    totals = defaultdict(int)
    for e in outstanding:
        d = e['details']
        if d['indicative_notional_cents'] is not None:
            totals[d['currency']] += d['indicative_notional_cents']
    summary.update({f'outstanding_indicative_notional_{currency}_cents': total for currency, total in totals.items()})
    details, history = [], []
    for e in exceptions:
        for d in e['details']['discrepancies']:
            details.append({'exception_id': e['id'], 'trade_id': e['trade_id'], 'status': e['status'], **d})
        history.extend(repository.history(e['id']))
    with repository.connect() as db:
        trades = [dict(r) for r in db.execute('SELECT * FROM trades WHERE run_id=? ORDER BY id', (run_id,))]
    counts = pd.DataFrame(details).groupby('type').size().reset_index(name='individual_discrepancies') if details else pd.DataFrame(columns=['type', 'individual_discrepancies'])
    return {'Summary': pd.DataFrame([{'metric': k, 'value': v} for k, v in summary.items()]),
            'Exceptions': exception_frame(exceptions), 'Outstanding': exception_frame(outstanding),
            'Discrepancies': pd.DataFrame(details), 'Type counts': counts,
            'Source rows': pd.DataFrame(trades), 'Status history': pd.DataFrame(history)}


def csv_bytes(frame):
    return safe_frame(frame).to_csv(index=False).encode('utf-8-sig')


def excel_bytes(tables):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter', engine_kwargs={'options': {'strings_to_formulas': False, 'strings_to_urls': False}}) as writer:
        for name, frame in tables.items():
            safe_frame(frame).to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes(1, 0)
            if len(frame.columns):
                sheet.autofilter(0, 0, len(frame), len(frame.columns) - 1)
                sheet.set_column(0, len(frame.columns) - 1, 24)
    return output.getvalue()
