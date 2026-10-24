"""Exercise real Streamlit rendering and a simulated analyst workflow."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_sample_and_resolution(tmp_path, monkeypatch):
    app_path = Path(__file__).resolve().parents[1] / 'app.py'
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(app_path), default_timeout=45).run()
    assert not app.exception
    assert any('Load the simulated internal database' in item.value for item in app.info)
    assert len(app.get('file_uploader')) == 1
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert [m.value for m in app.metric] == ['2,000', '935', '65', '93.5%']
    state = next(widget for widget in app.selectbox if widget.label == 'New status')
    state.select('Resolved')
    next(button for button in app.button if button.label == 'Save status change').click().run()
    assert not app.exception
    assert any('resolution note' in error.value for error in app.error)
    app.text_area[0].input('Verified against simulated confirmation')
    next(button for button in app.button if button.label == 'Save status change').click().run()
    assert not app.exception
    from tradeops.database import Repository
    repository = Repository(tmp_path / 'data' / 'tradeops.sqlite3')
    assert repository.exceptions(1)[0]['status'] == 'Resolved'
    import json
    assert json.loads(repository.runs()[0]['source_metadata_json'])['internal_source'] == 'database_snapshot'
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert len(repository.runs()) == 1
    assert repository.exceptions(1)[0]['status'] == 'Resolved'
    app.sidebar.number_input[0].set_value(43)
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert len(repository.runs()) == 2
