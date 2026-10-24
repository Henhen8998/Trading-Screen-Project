"""Small examples make the reconciliation policy easy to inspect."""
import pandas as pd
import pytest

from tradeops.engine import FIELDS, cents, read_csv, reconcile
from tradeops.synthetic import generate


@pytest.fixture
def trade():
    return dict(zip(FIELDS, ['T1', 'ALFA_SIM', 'BUY', '100', '10.00', '2026-01-05', '2026-01-06', 'USD', 'Fictional North']))


def pair(trade, **changes):
    return pd.DataFrame([trade]), pd.DataFrame([trade | changes])


def kinds(result):
    return {(e['trade_id'], d['type']) for e in result.exceptions for d in e['discrepancies']}


def test_exact_match(trade):
    result = reconcile(*pair(trade))
    assert result.matched == 1
    assert result.summary['match_rate'] == 1
    assert not result.exceptions


@pytest.mark.parametrize('price,broken', [('10.00', False), ('10.01', False), ('9.99', False), ('10.02', True), ('9.98', True)])
def test_price_boundary(trade, price, broken):
    result = reconcile(*pair(trade, price=price))
    assert bool(result.exceptions) == broken
    if broken:
        assert result.exceptions[0]['severity'] == 'Low'


def test_quantity_and_exact_notional(trade):
    item = reconcile(*pair(trade, quantity='110')).exceptions[0]
    assert item['quantity_difference'] == -10
    assert item['price_difference_cents'] == 0
    assert item['indicative_notional_cents'] == 10000
    assert item['severity'] == 'Medium'
    assert cents('0.29') == 29


@pytest.mark.parametrize('field,value,kind', [('symbol', 'OTHER_SIM', 'SYMBOL'), ('side', 'SELL', 'SIDE'),
                                          ('currency', 'EUR', 'CURRENCY'), ('settlement_date', '2026-01-07', 'SETTLEMENT_DATE')])
def test_fields(trade, field, value, kind):
    result = reconcile(*pair(trade, **{field: value}))
    assert kinds(result) == {('T1', kind)}
    if field == 'currency':
        assert result.exceptions[0]['indicative_notional_cents'] is None


@pytest.mark.parametrize('missing', ['internal', 'broker'])
def test_missing(trade, missing):
    full, empty = pd.DataFrame([trade]), pd.DataFrame(columns=FIELDS)
    result = reconcile(empty, full) if missing == 'internal' else reconcile(full, empty)
    assert kinds(result) == {('T1', f'MISSING_{missing.upper()}')}
    assert result.exceptions[0]['indicative_notional_cents'] == 100000
    assert len(result.rows) == 1


@pytest.mark.parametrize('source', ['internal', 'broker'])
def test_duplicates_quarantined(trade, source):
    duplicate, unique = pd.DataFrame([trade, trade]), pd.DataFrame([trade | {'quantity': '200'}])
    result = reconcile(duplicate, unique) if source == 'internal' else reconcile(unique, duplicate)
    assert kinds(result) == {('T1', f'DUPLICATE_{source.upper()}')}
    assert len(result.rows) == 3 and result.matched == 0
    assert result.exceptions[0]['indicative_notional_cents'] is None


def test_multiple_discrepancies(trade):
    result = reconcile(*pair(trade, quantity='110', price='10.02', side='SELL'))
    assert len(result.exceptions) == 1
    assert result.summary['individual_discrepancies'] == 3
    assert result.exceptions[0]['indicative_notional_cents'] == 10220
    assert result.exceptions[0]['severity'] == 'High'


@pytest.mark.parametrize('field,value', [('quantity', '-1'), ('quantity', '1.2'), ('price', 'NaN'),
                                       ('price', 'Infinity'), ('price', '10.001'), ('price', '0'),
                                       ('side', 'LONG'), ('currency', 'usd'), ('settlement_date', '2026-01-04'),
                                       ('trade_date', '01/05/2026'), ('symbol', '')])
def test_invalid_rows_retained(trade, field, value):
    result = reconcile(*pair(trade, **{field: value}))
    assert kinds(result) == {('T1', 'INVALID_INPUT')}
    assert len(result.rows) == 2 and result.matched == 0
    assert result.exceptions[0]['broker'][0][field] == value


def test_blank_ids_do_not_match_or_collide(trade):
    result = reconcile(pd.DataFrame([trade | {'trade_id': ''}, trade | {'trade_id': '__invalid_internal_2'}]),
                       pd.DataFrame([trade | {'trade_id': ''}, trade | {'trade_id': '__invalid_internal_2'}]))
    assert result.matched == 1
    assert len(result.exceptions) == 2
    assert result.summary['invalid_rows_without_id'] == 2


def test_schema_and_tolerance(trade):
    with pytest.raises(ValueError, match='Missing required'):
        read_csv(b'trade_id\nT1\n')
    with pytest.raises(ValueError):
        read_csv(b'')
    with pytest.raises(ValueError):
        reconcile(*pair(trade), tolerance_cents=-1)
    with pytest.raises(ValueError):
        reconcile(pd.DataFrame(), pd.DataFrame())


def test_empty_valid_schema():
    result = reconcile(pd.DataFrame(columns=FIELDS), pd.DataFrame(columns=FIELDS))
    assert result.summary['match_rate'] is None
    assert not result.exceptions


@pytest.mark.parametrize('seed', [0, 42, 2027])
def test_ground_truth(seed):
    internal, broker, truth = generate(seed)
    result = reconcile(internal, broker)
    expected = set(zip(truth['trade_id'], truth['type']))
    assert kinds(result) == expected
    assert len(result.exceptions) == 65
    assert result.matched == 935
    assert result.summary['individual_discrepancies'] == 70
    assert len(internal) == len(broker) == 1000
    for first, second in zip(generate(seed), generate(seed)):
        pd.testing.assert_frame_equal(first, second)


def test_configuration_and_zero_tolerance(trade):
    assert kinds(reconcile(*pair(trade, price='10.01'), tolerance_cents=0)) == {('T1', 'PRICE')}
    with pytest.raises(ValueError):
        generate(count=10)


@pytest.mark.parametrize('content', [b'a,a\n1,2\n', b'a,b\n1,2,3\n', b'a,b\n\n', b'a,b\n"unclosed,2'])
def test_malformed_csv_is_explicitly_rejected(content):
    with pytest.raises(ValueError, match='Cannot read CSV'):
        read_csv(content)


def test_raw_values_are_preserved(trade):
    result = reconcile(*pair(trade, symbol=' ALFA_SIM '))
    assert result.matched == 1
    assert result.rows[1]['raw_values']['symbol'] == ' ALFA_SIM '
