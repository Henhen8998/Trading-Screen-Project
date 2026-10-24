# Local verification

Verified on Windows with Python 3.12.10 on 2026-10-17.

| Check | Observed result |
|---|---|
| `python -m pytest -q` | Current application including manual walkthrough: 68 passed in 13.35 seconds |
| `python -m pip check` | No broken requirements found |
| `git diff --check` | No whitespace errors reported |
| Streamlit server | Started on 127.0.0.1:8501 |
| `GET /_stcore/health` | HTTP 200, body `ok` |
| Generated default sample | 2,000 total source rows, 1,000 identifiable IDs, 935 matched IDs, 65 exception records, 70 discrepancies, 93.5% match rate |
| Report generation | Seven CSV reports and a seven-sheet Excel workbook written under `data/reports/` |
| Internal database integration | Direct SQL snapshot extraction, read-only connections, full-population missing-side checks, malformed internal rows, snapshot integrity checks, provenance exports, repeat imports, and historical database upgrade all passed |
| Manual single-trade walkthrough | Matching inputs, quantity/notional example, tolerance boundaries, missing sides, differing IDs, invalid input, repeat-import status preservation, and the actual Streamlit form/resolution flow all passed |

The current dashboard exposes only the broker CSV upload. The internal source is `data/internal_trades.sqlite3`; the reconciliation repository remains `data/tradeops.sqlite3`. A database-backed sample was reconciled as run 2 with the same expected fixture counts. The original CSV-backed run 1 was preserved. Live-test stages also use the internal database path.

The test duration is an observed test-run duration, not a trade-processing benchmark. Fixture counts reflect intentionally injected errors, not production accuracy. Ground-truth equality is checked for seeds 0, 42, and 2027.

The Streamlit AppTest tests rendered the actual app and exercised sample creation, mandatory resolution-note validation, resolution persistence, repeat-import preservation, creation of a second run/trend, and all nine stages of the watchable live-test page. An interactive visual browser review was not performed because no browser was available through the automation interface. Upload parsing is covered in engine/repository tests; an actual browser upload/download interaction was not exercised.

Tested direct dependency versions: Pandas 2.3.3, Streamlit 1.66.0, Plotly 6.9.0, XlsxWriter 3.2.9, Pytest 9.1.1. `requirements.txt` permits compatible versions within bounded major ranges. Re-run the tests after dependency updates.

To reproduce from the project directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m streamlit run app.py
```
