"""Watch a real reconciliation and exception workflow, one stage at a time."""
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from tradeops.live_demo import LiveDemo, STEPS

st.set_page_config(page_title='TradeOps | Live test', page_icon='▶', layout='wide')
st.title('TradeOps — watch a live test')
st.caption('SIMULATED DATA • Real reconciliation, SQLite writes, validation, and report generation • Separate demo database')
st.write('Internal database → reconciliation ← broker CSV. Each stage performs a real operation and checks its result. Watch the source comparison, workflow status, and history change below.')

if 'live_demo' not in st.session_state:
    path = Path('data/live_tests') / uuid4().hex / 'demo.sqlite3'
    st.session_state.live_demo = LiveDemo(path)
    st.session_state.playing = st.query_params.get('autoplay') == '1'
    st.session_state.failure = None

a, b, c = st.columns([1, 1, 3])
if a.button('Start / resume', type='primary'):
    st.session_state.playing = True
if b.button('Pause'):
    st.session_state.playing = False
with c:
    st.caption('One stage every 5 seconds. Keep this tab open while watching.')


@st.fragment(run_every=5)
def live_view():
    demo = st.session_state.live_demo
    if st.session_state.playing and not demo.done and not st.session_state.failure:
        try:
            demo.advance()
        except Exception as exc:
            st.session_state.failure = f'{type(exc).__name__}: {exc}'
            st.session_state.playing = False
    st.progress(demo.next_step / len(STEPS), text=f'{demo.next_step} / {len(STEPS)} checks passed')
    if st.session_state.failure:
        st.error(f'Test stopped: {st.session_state.failure}')
    elif demo.done:
        st.success('LIVE TEST COMPLETE — all 9 checks passed.')
    elif st.session_state.playing:
        st.info(f'Next: {STEPS[demo.next_step]}')
    else:
        st.info('Ready / paused. Press Start / resume to watch the test.')
    if demo.result:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric('Source rows', len(demo.result.rows))
        k2.metric('Matched IDs', demo.result.matched)
        k3.metric('Exception records', len(demo.result.exceptions))
        k4.metric('Match rate', f'{demo.result.summary["match_rate"]:.1%}')
    if demo.events:
        latest = demo.events[-1]
        st.subheader(f"Stage {latest['step']}: {latest['check']}")
        st.write(latest['detail'])
    if demo.exception_id:
        selected = next(e for e in demo.repository.exceptions(demo.run_id) if e['id'] == demo.exception_id)
        st.subheader(f"{selected['trade_id']} · {selected['status']}")
        left, right = st.columns(2)
        left.write('**Internal record**')
        left.dataframe(pd.DataFrame(selected['details']['internal']), hide_index=True, width='stretch')
        right.write('**Broker confirmation**')
        right.dataframe(pd.DataFrame(selected['details']['broker']), hide_index=True, width='stretch')
        st.write('**Status history (UTC)**')
        st.dataframe(pd.DataFrame(demo.repository.history(demo.exception_id)), hide_index=True, width='stretch')
    st.subheader('Live check log')
    if demo.events:
        st.dataframe(pd.DataFrame(demo.events), hide_index=True, width='stretch')
    if demo.done:
        st.download_button('Download tested exception CSV', demo.csv, 'live_test_exceptions.csv', 'text/csv')
        st.download_button('Download tested Excel report', demo.workbook, 'tradeops_live_test.xlsx',
                           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        st.link_button('Open the full TradeOps dashboard', 'http://127.0.0.1:8501')
    st.caption(f'Demo database: {demo.repository.path}')


live_view()
