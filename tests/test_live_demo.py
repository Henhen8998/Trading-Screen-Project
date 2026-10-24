from pathlib import Path

from streamlit.testing.v1 import AppTest

from tradeops.live_demo import LiveDemo, STEPS


def test_live_demo_all_stages(tmp_path):
    demo = LiveDemo(tmp_path / 'demo.sqlite3')
    for _ in STEPS:
        demo.advance()
    assert demo.done
    assert len(demo.events) == 9
    assert all(e['result'] == 'PASS' for e in demo.events)
    assert (tmp_path / 'tradeops_live_test.xlsx').is_file()
    assert (tmp_path / 'exceptions.csv').is_file()
    demo.advance()
    assert len(demo.events) == 9


def test_live_demo_page(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'live_test.py'
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    # Explicit reruns advance the same fragment without waiting for its timer.
    for _ in range(8):
        app.run()
    assert not app.exception
    assert any('all 9 checks passed' in item.value for item in app.success)
