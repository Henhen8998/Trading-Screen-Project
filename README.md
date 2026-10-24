# Trading Operations Project

## TradeOps — Automated Trade Reconciliation & Exception Management System

A locally runnable portfolio project comparing internal equity trades with fictional broker confirmations. **All sample data is simulated.** No accounts, market connections, or API keys are required.

Built for a Drexel Chemical Engineering student with a Finance minor preparing for trading operations and technical business analyst co-op interviews. Emphasis: explainable controls, exact monetary arithmetic, SQL, and exception investigation.

### Windows PowerShell setup

From this directory, install Python if needed:

```powershell
winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
```

Use the executable explicitly to avoid Microsoft Store aliases. No activation or execution-policy change is needed:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m tradeops.internal_store --seed 42 --output data
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open **http://127.0.0.1:8501** and click **Load demo database & reconcile**, or select an internal database snapshot and upload only `data/broker_trades.csv`. Stop with Ctrl+C. Python 3.11+ is supported; these commands use Python 3.12's standard per-user installation path. Substitute your absolute Python executable if installed elsewhere.

### Why the internal side uses a database

Internal trade records are supplied by a simulated upstream trade-capture database, rather than an analyst manually exporting and uploading a file. This makes the source and selected population explicit, removes a manual internal export/upload step, and allows SQL-based access. CSV remains the external broker-file format in this educational integration.

The application has two separate database roles:

- `data/internal_trades.sqlite3`: simulated internal source, containing versioned snapshots and trade rows. Demo seeding represents upstream capture. Reconciliation queries the chosen snapshot using a read-only connection.
- `data/tradeops.sqlite3`: reconciliation evidence, exceptions, and workflow history. It retains copies of the values actually compared so old results remain explainable.

The source query selects **all rows in the chosen snapshot**, not just IDs present in the broker file; otherwise missing broker confirmations could disappear from the control. Use a broker file covering the same dates and population as the selected snapshot. The current fixture covers January 5–9, 2026; the snapshot selector shows its seed and row count. The demo button creates the matching broker data and offers it for download. New seeds append snapshots; they never replace earlier ones.

Database storage alone does not establish correctness. Validation, duplicate detection, price rules, and preservation of source evidence still apply. Source columns are text in this simulated landing table so deliberately malformed records can be tested. It is not a full trading ledger or OMS. Real integrations may expose approved views, read replicas, APIs, feeds, or scheduled extracts; CSV can still be valid. This project makes no claim about SIG's implementation. See the interview guide for a concise explanation.

### Five-minute demo

**To explain one trade manually:** choose **Single-trade walkthrough** in the sidebar's Workspace selector. Enter an internal record and broker confirmation, then click **Reconcile this trade**. Both default to WALK001, BUY 100 shares at $10.00. Internal entry is saved to an isolated source database and read back through the normal reconciliation path; the broker form simulates an external confirmation without requiring a file upload. Scenarios and workflow history are saved under `data/manual_demo/`, separately from portfolio runs.

First reconcile identical values. Then change only broker quantity to 110: the result shows one QUANTITY discrepancy, internal-minus-broker quantity −10, and USD 100.00 indicative gross notional difference. Investigate and resolve with a note. Reset quantity to 100 before testing broker prices 10.01 and 10.02 against internal 10.00: the first is within the default inclusive tolerance, the second breaks. Uncheck a side to demonstrate a missing record. Different trade IDs produce two unmatched records. Both sides absent is rejected.

The walkthrough preserves prior scenarios, provides source-by-source values and reports, and reopens identical scenarios without losing workflow history. Form edits take effect only when submitted; the selected saved scenario is clearly labeled. Manual data entry is a teaching simulation of upstream capture and external confirmation, not a production trade-booking interface.

For an automated, watchable live test in a separate database, run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run live_test.py --server.port 8502
```

Open **http://127.0.0.1:8502/?autoplay=1**. Nine assertion-backed stages run five seconds apart, showing a source comparison, resolution-note validation, status history, import idempotency, and report generation. Pause/resume is available. Each browser session uses a separate database under `data/live_tests/`.

1. Load seed 42 into the internal database and reconcile with the default one-cent tolerance.
2. Review severity and discrepancy breakdowns.
3. Filter to QUANTITY, inspect both source records, and move an exception to Investigating.
4. Resolve with a note; review the timestamped status history.
5. Reconcile the same internal snapshot and broker file: the same run and workflow remain.
6. Download the Excel report. Generate another seed for a run trend.

Generation starts with **1,000 base IDs**. Five missing rows and five added duplicate rows on each side leave **1,000 source-database rows** and **1,000 broker-file rows**. The default fixture has **65 exception records**, **70 individual discrepancies**, and **935 fully reconciled IDs**. These are injected fixture properties, not performance metrics. Tests compare detected `(trade_id, type)` pairs with the independent injection manifest, exported as `ground_truth.csv`. The original `python -m tradeops.synthetic` command remains available to export both sides as CSV test fixtures; internal CSVs are no longer uploaded through the dashboard.

### Reconciliation policies

| Concern | Behavior |
|---|---|
| Matching | Exact case-sensitive trade ID after outer whitespace trimming |
| Required columns | trade_id, symbol, side, quantity, price, trade_date, settlement_date, currency, broker; extra columns retained |
| Validation | Positive integer quantity; positive finite cent-precision price; BUY/SELL; three uppercase currency letters; ISO dates; settlement cannot precede trade date; required fields nonblank |
| File errors | Unreadable, ragged, blank-record, or duplicate-header CSVs rejected explicitly before creating a run |
| Invalid rows | Original values and errors retained; usable IDs quarantined on both sides; blank IDs become separate source-row exceptions |
| Duplicates | Detect per source before joining; quarantine entire ID and counterpart; never choose an arbitrary duplicate |
| Compared fields | Quantity, price, symbol, side, currency, settlement date; broker and trade date required but not compared in this MVP |
| Price tolerance | Default absolute difference ≤ 1 cent/share accepted, inclusive; configurable; no relative tolerance |
| Money | Parse with Decimal, calculate with integer cents; no FX conversion |
| Signed differences | Internal minus broker quantity and per-share price |
| Indicative notional | Same currency: absolute difference of recorded quantity × price values; missing records use available-side gross notional |
| Unavailable notional | Invalid, duplicate, or currency-conflicting records; never imputed as zero |
| Severity | High: invalid/duplicate/missing/symbol/side/currency; Medium: quantity/settlement; Low: price only; highest applicable wins |

The one-cent tolerance illustrates an agreed rounding allowance, **not a universal trading standard**. One cent/share can be material at large quantity. Within-tolerance values remain in source data but do not create a price exception. Indicative notional can mask offsetting quantity/price differences or side errors. It is **not P&L, realized loss, net exposure, or a payment instruction**, and it does not determine severity.

### Metrics and workflow

- **Source rows processed:** internal plus broker rows, including invalid and duplicate rows.
- **Matched trade IDs:** valid unique pairs without discrepancies beyond tolerance.
- **Exception records:** one per affected identifiable ID plus one per invalid blank-ID row. Quarantined records get validation/duplicate findings; fields are not compared.
- **Individual discrepancies:** all findings within exception records; a trade may have several.
- **Match rate:** matched IDs / distinct nonblank IDs across both files, including quarantined IDs. Empty denominator shows N/A. Blank-ID rows are counted separately; this rate alone is not a data-quality score.
- **Outstanding:** Open or Investigating. Resolution requires a note; reopening is supported. Resolving records review and does not change sources or original reconciliation KPIs.

SQLite stores immutable run snapshots, original and normalized source fields, exception details, and UTC status history under `data/tradeops.sqlite3`. Bound SQL parameters, foreign keys, constraints, and transactions are used. The internal snapshot content hash, broker-file hash, source type, tolerance, and engine version form a unique import fingerprint. Identical inputs preserve workflow; broker CSV reformatting creates a new run. Source snapshot ID, capture timestamp, database path, and content hash are recorded with each new run and included in its summary report. Source hash/row-count checks reject altered snapshots. Back up both databases with the app stopped. No reset/delete button is provided.

Existing two-CSV runs and resolution notes remain available as historical runs. An additive metadata-column upgrade preserves the original database; the dashboard labels those runs as historical CSV inputs. The old two-CSV repository method is retained for compatibility tests, not exposed as an internal upload control.

### Reports and layout

Reports export summary, all exceptions, outstanding exceptions, individual discrepancies, type counts, source rows, and status history as CSVs and a seven-sheet `.xlsx` workbook. These cover the selected run at export time; the workspace separately exports filtered exceptions. Money uses integer cents; outstanding indicative totals are grouped by currency. User-supplied spreadsheet formula prefixes are escaped.

```text
app.py                     Streamlit dashboard
tradeops/engine.py         Validation, quarantine, outer join, comparison
tradeops/synthetic.py      Seeded sample and injection manifest
tradeops/internal_store.py Internal source snapshots and read-only SQL extraction
tradeops/manual.py         Single-trade scenario persistence using the same pipeline
tradeops/walkthrough.py    Manual interview walkthrough screen
tradeops/database.py       SQLite persistence and workflow
tradeops/reporting.py      CSV and Excel exports
tests/                     Engine, persistence, exports, dashboard checks
data/                     Generated CSVs/database (gitignored)
```

Study the engine and its tests first. See [ARCHITECTURE.md](ARCHITECTURE.md) and [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md) for the data flow and interview preparation.

### Limits

Single-user educational batch application. No authentication, independent approval, source corrections, real feeds, exchange calendars, fees, corporate actions, allocations, options lifecycle, ETF baskets, FX conversion, or treasury payments. Synthetic settlement uses the next weekday and ignores holidays. Currency validation checks format, not an ISO registry. Input is UTF-8 CSV, BOM accepted, decimal-point prices without thousands separators. Trade ID matching assumes shared stable IDs. Local history is not tamper-proof or an institutional control system. No scalability benchmark is claimed.

### Troubleshooting after code updates

If an already running app reports `AttributeError: 'Repository' object has no attribute 'import_internal_snapshot'`, stop Streamlit with Ctrl+C in its terminal and restart it:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Then refresh the browser. A long-running server can retain an older imported Python class after source files change; refreshing the page alone does not restart that Python process. Restarting preserves the SQLite databases and saved workflow history.
