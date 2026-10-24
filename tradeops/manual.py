"""Persist a single manually entered scenario using the normal pipeline."""
from pathlib import Path

import pandas as pd

from tradeops.database import Repository
from tradeops.engine import FIELDS
from tradeops.internal_store import InternalTradeStore


def run_single_trade(internal, broker, tolerance_cents=1, directory='data/manual_demo'):
    """Stage internal capture, then reconcile a simulated broker confirmation.

    None means the record is absent on that side. Both absent is not a scenario.
    Manual broker input becomes an in-memory CSV using the existing file adapter;
    internal input goes into SQLite and is queried through the normal read path.
    Reconciliation source rows preserve the broker evidence with the saved run.
    """
    if internal is None and broker is None:
        raise ValueError('Include at least one side to demonstrate a trade')
    for record in (internal, broker):
        if record is not None and set(record) != set(FIELDS):
            raise ValueError('Each trade must contain exactly the required fields')
    root = Path(directory)
    store = InternalTradeStore(root / 'internal.sqlite3')
    repository = Repository(root / 'results.sqlite3')
    internal_frame = pd.DataFrame([] if internal is None else [internal], columns=FIELDS)
    broker_frame = pd.DataFrame([] if broker is None else [broker], columns=FIELDS)
    snapshot_id = store.seed_snapshot(internal_frame, seed=0)
    run_id, created = repository.import_internal_snapshot(
        store, snapshot_id, broker_frame.to_csv(index=False).encode(), tolerance_cents)
    return run_id, created
