"""Validate and reconcile simulated equities without floating-point money."""
from __future__ import annotations

from dataclasses import dataclass
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
import re

import pandas as pd

FIELDS = ['trade_id', 'symbol', 'side', 'quantity', 'price', 'trade_date',
          'settlement_date', 'currency', 'broker']
ENGINE_VERSION = '1'
HIGH = {'INVALID_INPUT', 'DUPLICATE_INTERNAL', 'DUPLICATE_BROKER',
        'MISSING_INTERNAL', 'MISSING_BROKER', 'SYMBOL', 'SIDE', 'CURRENCY'}


def cents(value: str) -> int:
    """Reject nonfinite, nonpositive, and sub-cent monetary inputs."""
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number * 100 != (number * 100).to_integral_value():
            raise ValueError('price must be positive with at most two decimal places')
        return int(number * 100)
    except InvalidOperation as exc:
        raise ValueError('invalid price') from exc


@dataclass
class Result:
    rows: list[dict]
    exceptions: list[dict]
    matched: int
    identifiable_ids: int
    tolerance_cents: int

    @property
    def summary(self) -> dict:
        return {'source_rows_processed': len(self.rows), 'identifiable_trade_ids': self.identifiable_ids,
                'matched_records': self.matched, 'exception_records': len(self.exceptions),
                'individual_discrepancies': sum(len(e['discrepancies']) for e in self.exceptions),
                'invalid_rows_without_id': sum(not r['trade_id'] for r in self.rows),
                'match_rate': self.matched / self.identifiable_ids if self.identifiable_ids else None}


def read_csv(content: bytes) -> pd.DataFrame:
    try:
        # Check width before Pandas can infer an index from an extra CSV field.
        records = list(csv.reader(StringIO(content.decode('utf-8-sig')), strict=True))
        if not records or not records[0]:
            raise ValueError('CSV is empty')
        if len(set(records[0])) != len(records[0]):
            raise ValueError('Duplicate CSV column names')
        for number, record in enumerate(records[1:], start=2):
            if len(record) != len(records[0]):
                raise ValueError(f'CSV record {number} has {len(record)} fields; expected {len(records[0])}')
        frame = pd.read_csv(BytesIO(content), dtype=str, keep_default_na=False, skip_blank_lines=False)
    except (ValueError, UnicodeError, csv.Error, pd.errors.ParserError) as exc:
        raise ValueError(f'Cannot read CSV: {exc}') from exc
    missing = set(FIELDS) - set(frame.columns)
    if missing:
        raise ValueError(f'Missing required columns: {", ".join(sorted(missing))}')
    return frame


def validate(frame: pd.DataFrame, source: str) -> list[dict]:
    missing = set(FIELDS) - set(frame.columns)
    if missing:
        raise ValueError(f'Missing required columns: {sorted(missing)}')
    rows = []
    for position, raw in enumerate(frame.fillna('').to_dict('records'), start=2):
        raw_values = {key: str(value) for key, value in raw.items()}
        values = {key: value.strip() for key, value in raw_values.items()}
        errors = []
        for field in FIELDS:
            if not values[field]:
                errors.append(f'{field}: required')
        if not re.fullmatch(r'[1-9][0-9]*', values['quantity']):
            errors.append('quantity: positive integer required')
        try:
            price = cents(values['price'])
        except ValueError as exc:
            price = None
            errors.append(f'price: {exc}')
        if values['side'] not in {'BUY', 'SELL'}:
            errors.append('side: BUY or SELL required')
        if not re.fullmatch('[A-Z]{3}', values['currency']):
            errors.append('currency: three uppercase letters required')
        dates = {}
        for field in ('trade_date', 'settlement_date'):
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', values[field]):
                    raise ValueError()
                dates[field] = date.fromisoformat(values[field])
            except ValueError:
                errors.append(f'{field}: ISO date required')
        if len(dates) == 2 and dates['settlement_date'] < dates['trade_date']:
            errors.append('settlement_date: precedes trade_date')
        rows.append({'source': source, 'row_number': position, 'trade_id': values['trade_id'],
                     'values': values, 'raw_values': raw_values, 'errors': errors, 'price_cents': price})
    return rows


def reconcile(internal: pd.DataFrame, broker: pd.DataFrame, tolerance_cents: int = 1) -> Result:
    """Quarantine ambiguous IDs, then outer-join unique valid trades.

    Notional is an indicative difference in recorded gross values, never P&L.
    One cent per share is an educational absolute tolerance, inclusive at boundary.
    """
    if type(tolerance_cents) is not int or tolerance_cents < 0:
        raise ValueError('Tolerance must be a nonnegative integer number of cents')
    rows = validate(internal, 'internal') + validate(broker, 'broker')
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = row['trade_id'] or f"__invalid_{row['source']}_{row['row_number']}"
        # Tuple-like namespaces prevent blank-ID rows colliding with user IDs.
        key = ('id', key) if row['trade_id'] else ('row', key)
        groups.setdefault(key, []).append(row)
    exceptions = []
    valid = {'internal': [], 'broker': []}

    def exception(identifier, members, discrepancies, quantity_diff=None, price_diff=None, notional=None, currency=None):
        types = {d['type'] for d in discrepancies}
        severity = 'High' if types & HIGH else 'Medium' if types & {'QUANTITY', 'SETTLEMENT_DATE'} else 'Low'
        exceptions.append({'trade_id': identifier, 'severity': severity, 'discrepancies': discrepancies,
                           'quantity_difference': quantity_diff, 'price_difference_cents': price_diff,
                           'indicative_notional_cents': notional, 'currency': currency,
                           'internal': [r['values'] for r in members if r['source'] == 'internal'],
                           'broker': [r['values'] for r in members if r['source'] == 'broker']})

    for key, members in groups.items():
        issues = []
        for source in valid:
            count = sum(r['source'] == source for r in members)
            if count > 1:
                issues.append({'type': f'DUPLICATE_{source.upper()}', 'internal': count if source == 'internal' else None,
                               'broker': count if source == 'broker' else None})
        for row in members:
            if row['errors']:
                issues.append({'type': 'INVALID_INPUT', 'source': row['source'], 'row_number': row['row_number'],
                               'details': '; '.join(row['errors'])})
        if issues:
            exception(members[0]['trade_id'] or f"(blank ID: {members[0]['source']} row {members[0]['row_number']})", members, issues)
        else:
            for row in members:
                valid[row['source']].append(row)
    left = pd.DataFrame([{'trade_id': r['trade_id'], 'internal': r} for r in valid['internal']], columns=['trade_id', 'internal'])
    right = pd.DataFrame([{'trade_id': r['trade_id'], 'broker': r} for r in valid['broker']], columns=['trade_id', 'broker'])
    joined = left.merge(right, on='trade_id', how='outer', indicator=True, validate='one_to_one')
    matched = 0
    for _, pair in joined.iterrows():
        if pair['_merge'] != 'both':
            present = pair['internal'] if pair['_merge'] == 'left_only' else pair['broker']
            kind = 'MISSING_BROKER' if pair['_merge'] == 'left_only' else 'MISSING_INTERNAL'
            v = present['values']
            exception(pair['trade_id'], [present], [{'type': kind}], notional=int(v['quantity']) * present['price_cents'], currency=v['currency'])
            continue
        a, b = pair['internal'], pair['broker']
        av, bv = a['values'], b['values']
        qdiff = int(av['quantity']) - int(bv['quantity'])
        pdiff = a['price_cents'] - b['price_cents']
        issues = []
        for field in ('quantity', 'price', 'symbol', 'side', 'currency', 'settlement_date'):
            different = qdiff != 0 if field == 'quantity' else abs(pdiff) > tolerance_cents if field == 'price' else av[field] != bv[field]
            if different:
                issues.append({'type': field.upper(), 'internal': av[field], 'broker': bv[field]})
        if issues:
            comparable = av['currency'] == bv['currency']
            notional = abs(int(av['quantity']) * a['price_cents'] - int(bv['quantity']) * b['price_cents']) if comparable else None
            exception(pair['trade_id'], [a, b], issues, qdiff, pdiff, notional, av['currency'] if comparable else None)
        else:
            matched += 1
    return Result(rows, exceptions, matched, len({r['trade_id'] for r in rows if r['trade_id']}), tolerance_cents)
