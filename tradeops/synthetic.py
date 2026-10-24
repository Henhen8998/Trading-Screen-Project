"""Reproducible fictional trades and an independent injection manifest."""
import argparse
from datetime import date, timedelta
from pathlib import Path
import random

import pandas as pd

from tradeops.engine import FIELDS


def weekday_after(day):
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def generate(seed=42, count=1000):
    if count < 100:
        raise ValueError('At least 100 base trades required for controlled injection')
    rng = random.Random(seed)
    rows = []
    for index in range(count):
        day = date(2026, 1, 5) + timedelta(days=rng.randrange(5))
        price = rng.randrange(1000, 50001)
        rows.append(dict(zip(FIELDS, [f'SIM{index + 1:06}', rng.choice(['ALFA_SIM', 'BETA_SIM', 'GAMMA_SIM', 'DELTA_SIM']),
                    rng.choice(['BUY', 'SELL']), str(rng.randrange(1, 21) * 100), f'{price // 100}.{price % 100:02}',
                    day.isoformat(), weekday_after(day).isoformat(), 'USD', rng.choice(['Fictional North', 'Fictional East'])])))
    internal = [r.copy() for r in rows]
    broker = [r.copy() for r in rows]
    truth = []
    def mark(index, kind, source='broker'):
        truth.append({'trade_id': rows[index]['trade_id'], 'type': kind, 'source': source})
    for i in range(10):
        broker[i]['quantity'] = str(int(broker[i]['quantity']) + 100)
        mark(i, 'QUANTITY')
    for i in range(10, 20):
        price = int(broker[i]['price'].replace('.', '')) + 25
        broker[i]['price'] = f'{price // 100}.{price % 100:02}'
        mark(i, 'PRICE')
    for i in range(20, 30):
        broker[i]['settlement_date'] = weekday_after(date.fromisoformat(broker[i]['settlement_date'])).isoformat()
        mark(i, 'SETTLEMENT_DATE')
    for i in range(30, 35):
        broker[i]['quantity'] = str(int(broker[i]['quantity']) + 50)
        broker[i]['symbol'] = 'OTHER_SIM'
        mark(i, 'QUANTITY'); mark(i, 'SYMBOL')
    for i in range(35, 40):
        broker[i]['side'] = 'SELL' if broker[i]['side'] == 'BUY' else 'BUY'
        mark(i, 'SIDE')
    for i in range(40, 45):
        broker[i]['currency'] = 'EUR'
        mark(i, 'CURRENCY')
    for i in range(45, 50):
        internal.append(internal[i].copy()); mark(i, 'DUPLICATE_INTERNAL', 'internal')
    for i in range(50, 55):
        broker.append(broker[i].copy()); mark(i, 'DUPLICATE_BROKER')
    for i in range(55, 60):
        mark(i, 'MISSING_INTERNAL', 'internal')
    for i in range(60, 65):
        mark(i, 'MISSING_BROKER')
    internal = [r for r in internal if r['trade_id'] not in {rows[i]['trade_id'] for i in range(55, 60)}]
    broker = [r for r in broker if r['trade_id'] not in {rows[i]['trade_id'] for i in range(60, 65)}]
    return pd.DataFrame(internal), pd.DataFrame(broker), pd.DataFrame(truth)


def write_sample(directory='data', seed=42):
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    frames = generate(seed)
    for name, frame in zip(['internal_trades.csv', 'broker_trades.csv', 'ground_truth.csv'], frames):
        frame.to_csv(destination / name, index=False)
    return frames


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', default='data')
    args = parser.parse_args()
    write_sample(args.output, args.seed)
    print(f'Simulated CSV files written to {args.output}')
