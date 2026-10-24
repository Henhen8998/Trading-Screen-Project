"""Interview-friendly manual input screen; all rules use the existing engine."""
from datetime import date
import json

import pandas as pd
import streamlit as st

from tradeops.database import Repository
from tradeops.engine import FIELDS
from tradeops.manual import run_single_trade
from tradeops.reporting import csv_bytes, excel_bytes, report_tables

DIRECTORY = 'data/manual_demo'


def trade_fields(source):
    """Widget keys let both sides have familiar field labels."""
    prefix = f'manual_{source}_'
    values = {}
    values['trade_id'] = st.text_input('Trade ID', 'WALK001', key=prefix + 'trade_id')
    values['symbol'] = st.text_input('Symbol', 'ALFA_SIM', key=prefix + 'symbol')
    values['side'] = st.selectbox('Side', ['BUY', 'SELL'], key=prefix + 'side')
    values['quantity'] = st.text_input('Quantity', '100', key=prefix + 'quantity')
    values['price'] = st.text_input('Price per share', '10.00', key=prefix + 'price')
    values['trade_date'] = st.date_input('Trade date', date(2026, 1, 5), key=prefix + 'trade_date').isoformat()
    values['settlement_date'] = st.date_input('Settlement date', date(2026, 1, 6), key=prefix + 'settlement_date').isoformat()
    values['currency'] = st.text_input('Currency', 'USD', key=prefix + 'currency')
    values['broker'] = st.text_input('Broker', 'Fictional North', key=prefix + 'broker')
    return values


def render_walkthrough():
    st.subheader('Single-trade walkthrough')
    st.write('Enter what the firm recorded and what the broker confirmed. Use the same trade ID to compare fields, then change one value to demonstrate a break.')
    st.caption('SIMULATED manual entry. Internal input is saved to a separate demo source database before reconciliation. Broker input simulates an external confirmation. Portfolio runs are kept separately.')
    with st.expander('Suggested interview walkthrough'):
        st.markdown('1. Submit the default values: 100 shares at $10.00 on both sides.\n'
                    '2. Change broker quantity to 110 and submit again.\n'
                    '3. Explain the -10 share difference and USD 100.00 indicative notional discrepancy.\n'
                    '4. Mark the exception Investigating, then resolve it with a note.\n'
                    '5. Reset both quantities to 100; try a broker price of 10.01 versus 10.02 to show the inclusive one-cent tolerance.\n'
                    '6. Uncheck a side to show a missing record. Different trade IDs produce two unmatched records.')
    with st.form('single_trade_entry'):
        a, b = st.columns(2)
        with a:
            st.markdown('**Internal trade — simulated firm record**')
            include_internal = st.checkbox('Include internal trade', value=True, key='manual_include_internal')
            internal = trade_fields('internal')
        with b:
            st.markdown('**Broker trade — simulated confirmation**')
            include_broker = st.checkbox('Include broker trade', value=True, key='manual_include_broker')
            broker = trade_fields('broker')
        tolerance = st.number_input('Price tolerance (cents/share)', min_value=0, max_value=10000,
                                    value=1, step=1, key='manual_tolerance')
        if st.form_submit_button('Reconcile this trade', type='primary'):
            try:
                identifier, created = run_single_trade(internal if include_internal else None,
                                                       broker if include_broker else None, int(tolerance))
                st.session_state['manual_run_id'] = identifier
                st.session_state['manual_scenario_selection'] = identifier
                st.success('Scenario saved and reconciled.' if created else 'Identical scenario reopened; workflow preserved.')
            except (ValueError, OSError) as exc:
                st.error(str(exc))
    if 'manual_run_id' not in st.session_state:
        st.info('Submit the form to reconcile your first single-trade scenario.')
        return
    repository = Repository(f'{DIRECTORY}/results.sqlite3')
    runs = repository.runs()
    run_id = st.selectbox('Saved walkthrough scenario', [r['id'] for r in runs],
                          index=next(i for i, r in enumerate(runs) if r['id'] == st.session_state['manual_run_id']),
                          format_func=lambda identifier: f'Scenario {identifier}', key='manual_scenario_selection')
    run = next(r for r in runs if r['id'] == run_id)
    summary = json.loads(run['summary_json'])
    st.caption(f"Showing saved scenario {run_id} from {run['created_at']} (UTC). Form edits apply only after submission. Price tolerance: {run['tolerance_cents']} cents/share.")
    columns = st.columns(3)
    columns[0].metric('Matched trade IDs', summary['matched_records'])
    columns[1].metric('Exception records', summary['exception_records'])
    columns[2].metric('Individual discrepancies', summary['individual_discrepancies'])
    with repository.connect() as db:
        source_rows = [dict(r) for r in db.execute('SELECT source,values_json FROM trades WHERE run_id=? ORDER BY id', (run_id,))]
    captured = {r['source']: json.loads(r['values_json']) for r in source_rows}
    st.markdown('**Values actually compared**')
    st.dataframe(pd.DataFrame([{'field': field, 'internal': captured.get('internal', {}).get(field, '(absent)'),
                                'broker': captured.get('broker', {}).get(field, '(absent)')} for field in FIELDS]),
                 hide_index=True, width='stretch')
    exceptions = repository.exceptions(run_id)
    if not exceptions:
        st.success('Matched: both records agree within the configured price tolerance.')
    for item in exceptions:
        details = item['details']
        st.markdown(f"**{item['trade_id']} — {item['severity']} severity — {item['status']}**")
        st.dataframe(pd.DataFrame(details['discrepancies']), hide_index=True, width='stretch')
        a, b, c = st.columns(3)
        qdiff = details['quantity_difference']
        pdiff = details['price_difference_cents']
        a.write(f'Quantity difference: **{qdiff if qdiff is not None else "N/A"}** shares')
        b.write(f'Price difference: **{pdiff if pdiff is not None else "N/A"}** cents/share')
        notional = details['indicative_notional_cents']
        c.write('Indicative notional: **' + (f"{details['currency']} {notional // 100:,}.{notional % 100:02}" if notional is not None else 'N/A') + '**')
        st.caption('Signed differences are internal minus broker. Indicative notional compares recorded gross values; it is not P&L or realized loss.')
        with st.form(f"manual_workflow_{item['id']}"):
            states = ['Open', 'Investigating', 'Resolved']
            status = st.selectbox('New status', states, index=states.index(item['status']), key=f"manual_status_{item['id']}")
            note = st.text_area('Note (required to resolve)', key=f"manual_note_{item['id']}")
            if st.form_submit_button('Save walkthrough status'):
                try:
                    repository.update_status(item['id'], status, note)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        st.dataframe(pd.DataFrame(repository.history(item['id'])), hide_index=True, width='stretch')
    tables = report_tables(repository, run_id)
    st.download_button('Download walkthrough summary CSV', csv_bytes(tables['Summary']), f'scenario_{run_id}_summary.csv', 'text/csv')
    st.download_button('Download walkthrough Excel report', excel_bytes(tables), f'scenario_{run_id}.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
