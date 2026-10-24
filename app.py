"""Run with: python -m streamlit run app.py."""
import json

import pandas as pd
import plotly.express as px
import streamlit as st

from tradeops.database import Repository
from tradeops.internal_store import InternalTradeStore
from tradeops.reporting import csv_bytes, excel_bytes, exception_frame, report_tables

st.set_page_config(page_title='TradeOps | Reconciliation', page_icon='📊', layout='wide')
st.title('TradeOps')
st.caption('Automated Trade Reconciliation & Exception Management • SIMULATED DATA • Local educational application')
workspace = st.sidebar.radio('Workspace', ['Portfolio reconciliation', 'Single-trade walkthrough'])
if workspace == 'Single-trade walkthrough':
    from tradeops.walkthrough import render_walkthrough
    render_walkthrough()
    st.stop()
repository = Repository()
internal_store = InternalTradeStore()

with st.sidebar:
    st.header('Internal database & broker file')
    seed = st.number_input('Synthetic random seed', min_value=0, value=42, step=1)
    tolerance = st.number_input('Price tolerance (cents/share)', min_value=0, max_value=10000, value=1, step=1)
    st.caption('Inclusive tolerance: a difference equal to the limit is accepted.')
    if st.button('Load demo database & reconcile', type='primary'):
        try:
            snapshot_id, broker, _ = internal_store.seed_sample(int(seed))
            broker_bytes = broker.to_csv(index=False).encode()
            run_id, created = repository.import_internal_snapshot(internal_store, snapshot_id, broker_bytes, int(tolerance))
            st.session_state['active_run'] = run_id
            st.session_state['sample_broker'] = broker_bytes
            st.session_state['sample_seed'] = int(seed)
            st.session_state['internal_snapshot_id'] = snapshot_id
            st.success('New run saved.' if created else 'Existing run reopened; workflow preserved.')
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    st.divider()
    snapshots = internal_store.snapshots()
    snapshot_id = None
    if snapshots:
        snapshot_id = st.selectbox('Internal database snapshot', [s['id'] for s in snapshots],
                                   key='internal_snapshot_id',
                                   format_func=lambda identifier: next(f"Snapshot {s['id']} | seed {s['seed']} | {s['row_count']:,} rows" for s in snapshots if s['id'] == identifier))
        st.caption('Internal trades are queried automatically from the selected database snapshot.')
    else:
        st.info('Load the simulated internal database with the demo button above.')
    broker_upload = st.file_uploader('Broker confirmations CSV', type=['csv'])
    if st.button('Reconcile broker file against database', disabled=snapshot_id is None or broker_upload is None):
        try:
            run_id, created = repository.import_internal_snapshot(internal_store, snapshot_id, broker_upload.getvalue(), int(tolerance))
            st.session_state['active_run'] = run_id
            st.success('New run saved.' if created else 'Existing run reopened; workflow preserved.')
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    if 'sample_broker' in st.session_state:
        st.download_button('Download demo broker CSV', st.session_state['sample_broker'],
                           f"broker_seed_{st.session_state['sample_seed']}.csv", 'text/csv')
    st.caption('Use a broker file covering the same population as the selected snapshot. The entire internal snapshot is compared, including IDs absent from the broker file.')
    st.caption('Broker fields: trade_id, symbol, side, quantity, price, trade_date, settlement_date, currency, broker.')

runs = repository.runs()
if not runs:
    st.info('Load the simulated internal database in the sidebar, then reconcile the demo or upload a broker CSV.')
    st.markdown('**How it works:** validate → quarantine ambiguous records → match by trade ID → compare fields → investigate exceptions.')
    st.stop()

ids = [r['id'] for r in runs]
active = st.session_state.get('active_run', ids[0])
run_id = st.selectbox('Reconciliation run', ids, index=ids.index(active) if active in ids else 0,
                      format_func=lambda identifier: next(f"Run {r['id']} • {r['created_at']}" for r in runs if r['id'] == identifier))
run = next(r for r in runs if r['id'] == run_id)
summary = json.loads(run['summary_json'])
exceptions = repository.exceptions(run_id)
frame = exception_frame(exceptions)
st.caption(f"Run timestamp (UTC): {run['created_at']} | Engine {run['engine_version']} | Price tolerance: {run['tolerance_cents']} cents/share")
provenance = json.loads(run['source_metadata_json'])
if provenance.get('internal_source') == 'database_snapshot':
    snapshot = provenance['internal_snapshot']
    st.caption(f"Internal source: database snapshot {snapshot['id']} | Captured (UTC): {snapshot['created_at']} | {snapshot['row_count']:,} source rows. External source: broker CSV.")
else:
    st.caption('Historical run: internal and broker CSV inputs from the original application. Preserved for review.')
cols = st.columns(4)
cols[0].metric('Source rows processed', f"{summary['source_rows_processed']:,}")
cols[1].metric('Matched trade IDs', f"{summary['matched_records']:,}")
cols[2].metric('Exception records', f"{summary['exception_records']:,}")
cols[3].metric('Match rate', f"{summary['match_rate']:.1%}" if summary['match_rate'] is not None else 'N/A')
st.caption(f"Match rate = fully reconciled IDs ÷ {summary['identifiable_trade_ids']} distinct identifiable IDs. "
           f"{summary['individual_discrepancies']} individual discrepancies; {summary['invalid_rows_without_id']} source rows without an ID. "
           'Matched records include price differences within tolerance. Resolutions change workflow status, not original reconciliation results.')

overview, investigation, reports, trends = st.tabs(['Overview', 'Exception workspace', 'Reports', 'Run trends'])
with overview:
    if frame.empty:
        st.success('All identifiable trades reconciled within the configured tolerance.')
    else:
        left, right = st.columns(2)
        severity_counts = frame.groupby('severity').size().reset_index(name='Exception records')
        left.plotly_chart(px.bar(severity_counts, x='severity', y='Exception records', color='severity',
                                color_discrete_map={'High': '#c53f45', 'Medium': '#d68a23', 'Low': '#298c95'}, title='Record-level severity'), width='stretch')
        types = pd.DataFrame([d for e in exceptions for d in e['details']['discrepancies']])
        counts = types.groupby('type').size().reset_index(name='Individual discrepancies')
        right.plotly_chart(px.bar(counts, x='Individual discrepancies', y='type', orientation='h', title='Individual discrepancy types'), width='stretch')
        st.write(f"Outstanding exception records: **{sum(e['status'] != 'Resolved' for e in exceptions)}**")
    st.info('Indicative notional differences compare recorded gross trade values. They are not realized loss, P&L, cash exposure, or net risk. Different currencies are never summed.')

with investigation:
    if frame.empty:
        st.info('No exceptions for this run.')
    else:
        c1, c2, c3 = st.columns(3)
        statuses = c1.multiselect('Status', ['Open', 'Investigating', 'Resolved'], default=['Open', 'Investigating', 'Resolved'])
        severities = c2.multiselect('Severity', ['High', 'Medium', 'Low'], default=['High', 'Medium', 'Low'])
        all_types = sorted({d['type'] for e in exceptions for d in e['details']['discrepancies']})
        selected_types = c3.multiselect('Discrepancy type', all_types, default=all_types)
        query = st.text_input('Trade ID contains')
        filtered = frame[frame['status'].isin(statuses) & frame['severity'].isin(severities)
                         & frame['types'].map(lambda value: bool(set(value.split(', ')) & set(selected_types)))
                         & frame['trade_id'].str.contains(query, case=False, regex=False)]
        st.dataframe(filtered.drop(columns=['internal_values', 'broker_values']), hide_index=True, width='stretch')
        st.download_button('Download filtered exceptions CSV', csv_bytes(filtered), f'run_{run_id}_filtered_exceptions.csv', 'text/csv')
        if not filtered.empty:
            exception_id = st.selectbox('Inspect exception', filtered['exception_id'].tolist(),
                                         format_func=lambda identifier: next(f"#{e['id']} · {e['trade_id']} · {e['status']}" for e in exceptions if e['id'] == identifier))
            selected = next(e for e in exceptions if e['id'] == exception_id)
            details = selected['details']
            a, b = st.columns(2)
            a.subheader('Internal records')
            a.dataframe(pd.DataFrame(details['internal']), hide_index=True)
            b.subheader('Broker records')
            b.dataframe(pd.DataFrame(details['broker']), hide_index=True)
            st.dataframe(pd.DataFrame(details['discrepancies']), hide_index=True, width='stretch')
            if details['indicative_notional_cents'] is not None:
                amount = details['indicative_notional_cents']
                st.write(f"Indicative notional discrepancy: **{details['currency']} {amount // 100:,}.{amount % 100:02}**")
            else:
                st.caption('Indicative notional unavailable: ambiguous, invalid, or currency-conflicting records.')
            with st.form(f'workflow_{exception_id}'):
                states = ['Open', 'Investigating', 'Resolved']
                new_status = st.selectbox('New status', states, index=states.index(selected['status']))
                note = st.text_area('Note (required to resolve)')
                if st.form_submit_button('Save status change'):
                    try:
                        repository.update_status(exception_id, new_status, note)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            st.subheader('Status history (UTC)')
            st.dataframe(pd.DataFrame(repository.history(exception_id)), hide_index=True, width='stretch')

with reports:
    st.write('Reports cover the selected run and current workflow status. Monetary columns are integer cents. Source rows include retained validation errors.')
    tables = report_tables(repository, run_id)
    for name in ['Summary', 'Exceptions', 'Outstanding', 'Discrepancies', 'Type counts', 'Source rows', 'Status history']:
        st.download_button(f'{name} CSV', csv_bytes(tables[name]), f'run_{run_id}_{name.lower().replace(" ", "_")}.csv', 'text/csv')
    st.download_button('Download complete Excel workbook', excel_bytes(tables), f'tradeops_run_{run_id}.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', type='primary')
    st.dataframe(tables['Summary'], hide_index=True, width='stretch')

with trends:
    if len(runs) < 2:
        st.info('Import a different source pair or generate another seed to compare runs.')
    else:
        trend = pd.DataFrame([{'run_id': r['id'], 'timestamp_utc': r['created_at'], **json.loads(r['summary_json'])} for r in reversed(runs)])
        st.plotly_chart(px.line(trend, x='run_id', y='match_rate', markers=True, title='Match rate by reconciliation run'), width='stretch')
        st.dataframe(trend, hide_index=True, width='stretch')
        st.caption('Runs may contain different trade populations or tolerances; this is a descriptive comparison, not a performance benchmark.')
