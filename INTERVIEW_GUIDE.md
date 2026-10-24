# TradeOps interview guide

## A 60-second explanation

“I built a local Python application comparing simulated internal equity trades with broker confirmations. I validate inputs and quarantine duplicates or malformed IDs before an outer join. The engine flags missing records and multiple field differences, calculates money in integer cents, and persists each run in SQLite. A Streamlit dashboard lets an investigator review both sides, record status changes with resolution notes, and export reports. I test detection against an independent manifest of deliberately injected breaks. This is an educational batch application, not a live trading platform.”

Explain a concrete example and what you personally understand. Do not claim production experience from a simulated project.

## Why internal trades come from a database

**Interview-ready explanation:** “I separated internal trade capture from reconciliation. The application queries a simulated internal trade database through a read-only connection, then compares that snapshot against an uploaded broker confirmation file. This removes the analyst's manual internal export/upload step and makes the source population explicit. I preserve the queried values, snapshot identity, timestamps, and hashes with each run so results can be reproduced and investigated. SQLite keeps the project local and explainable; it is not a claim about SIG's database or architecture.”

**Why it helps:** a defined source, SQL-based selection, fewer manual file-handling steps, and a clear boundary between trade records and investigation results. A database is not automatically accurate, fast, secure, or production-ready: validation and control design still matter. Do not say that firms never use CSVs. Approved APIs, database views, feeds, and scheduled extracts are all possible integration patterns.

**How the code works:** demo seeding appends internal rows to `internal_trades.sqlite3`; the dashboard selects a snapshot; `load_snapshot` executes a parameterized SELECT over that whole snapshot using SQLite read-only mode; the engine receives a DataFrame directly and validates it alongside the broker file. Results and workflow go into `tradeops.sqlite3`, without editing the internal source. Original two-CSV runs are preserved and labeled historical.

**Why snapshots matter:** a live source can change during an investigation. Each source snapshot has a capture timestamp, row count, and content hash. The result retains the exact compared values. This is reproducible evidence, not a tamper-proof audit system. Never restrict internal rows to trade IDs in the broker file, because that hides missing broker records. The selected snapshot and broker file must cover the same agreed population.

**Why two database roles?** The source database represents what the simulated firm recorded; the results database records whether two sources agree and how exceptions were investigated. Storing exceptions in SQLite alone would not replace an internal CSV upload—the source itself must be queried.

**Source context:** DTCC describes reconciliation against firms' internal books and records in its [reconciliation discussion](https://www.dtcc.com/podcasts/2023/april/12/the-rise-of-reconciliation-requirements). That supports the internal-versus-external comparison concept; it does not establish a particular firm's database technology or interface.

## Trade lifecycle and operations

A simplified lifecycle is execution → trade capture → confirmation/allocation → matching and reconciliation → clearing/settlement → position and cash controls. Actual details vary by product and agreement. This project compares two post-trade records; it neither executes trades nor moves money or securities.

The sample uses next-weekday settlement, ignoring holidays. Validation checks settlement is not before trade date, then compares the two recorded dates. It does not establish correctness under real settlement conventions.

An analyst investigating a break would inspect source provenance, timestamps, confirmation details, and amendments; coordinate with the appropriate owner; rerun controls after correction; and record evidence. Clicking Resolved here records a simulated review, not proof of broker correction or settlement.

## Reconciliation walkthrough

1. Query internal snapshot rows through read-only SQL and parse the external broker CSV as text to avoid binary floating-point price conversion. Validate required columns and broker CSV structure.
2. Validate quantities, prices, dates, sides, currency format, and required fields. Preserve original values and source locations.
3. Detect duplicates per source and quarantine the entire ID, including its counterpart. Invalid rows with usable IDs follow the same policy. Blank IDs remain separate exceptions.
4. Outer-join unique valid IDs. Identify missing-side records and compare quantity, price, symbol, side, currency, and settlement date.
5. Apply the inclusive one-cent/share price tolerance. Keep every discrepancy for the trade and choose the highest severity.
6. Save a snapshot and initial Open history atomically. Investigate, resolve with a note, or reopen without changing the original result.

Example: internal 100 shares at $10.00 versus broker 110 at $10.02 yields quantity difference −10, per-share price difference −2 cents, and indicative notional `abs(100 × 1000 − 110 × 1002) = 10,220 cents`. This is one exception with two discrepancies. The $102.20 is not P&L: no market marks, position history, fees, or cash settlement proof are modeled.

Severity is a teaching policy: a large price-only break remains Low. Production prioritization would need agreed materiality, product context, settlement urgency, ownership, and service levels. Equal gross notionals can hide offsetting errors or a side mismatch.

## Database and workflow

SQLite provides local simplicity, constraints, SQL, and transactions without a server. Surrogate keys preserve duplicate trade IDs as evidence. Run/trade-ID and status indexes support review. Discrepancy rows distinguish individual findings from affected trades. JSON keeps source snapshots flexible without an elaborate schema.

The fingerprint includes internal snapshot content hash, broker-file hash, source type, tolerance, and engine version. Identical reruns reopen the same run and preserve statuses; changed inputs or policy create a new run. Rollback prevents partial imports. Parameter binding protects SQL value handling; foreign keys prevent orphaned records.

Open → Investigating → Resolved is the typical workflow; direct resolution and reopening are allowed. Every transition is timestamped in UTC, with mandatory notes on resolution. There is no user authentication or tamper-proof audit log. A team application would need ownership, access controls, concurrency policies, retention, and appropriate independent review.

## Relevance to target roles

These are transferable skills, not claims about SIG's proprietary systems or hiring requirements.

- **Trading Operations:** completeness controls, matching, investigation queues, settlement awareness, escalation, and documented resolution.
- **Equity Options Trading Operations:** validation and workflow transfer; actual options need contract identifiers, multipliers, expiry, exercise/assignment, and lifecycle rules absent here.
- **ETF Sales & Trading:** source comparison and reporting transfer; basket constituents, creations/redemptions, NAV-related information, and product settlement details are absent here.
- **Technical Business Analyst / FinOps / Treasury:** translating requirements into controls, SQL-backed history, reproducible analysis, cash/position reconciliation concepts, and clear discrepancy reporting. This app does not forecast cash, value positions, calculate funding, or execute payments.
- **Chemical Engineering:** conservation/accounting discipline, units, process troubleshooting, reproducible experiments, and separating evidence from inference.

## Twenty interview questions with answer guidance

1. **What does reconciliation solve?** Completeness and agreement across sources; agreement does not prove either source is economically correct.
2. **Why an outer join?** Inner joins hide missing trades; outer joins retain both missing-side categories.
3. **What is the trade-ID assumption?** Both sources share stable IDs. Real sources may use allocations, amendments, different identifiers, or composite matching.
4. **Why quarantine duplicates?** Many-to-many joins multiply rows and invent comparisons; preserve all evidence rather than arbitrarily dropping rows.
5. **Why integer cents?** Exact arithmetic after Decimal parsing. Sub-cent prices are rejected instead of silently rounded.
6. **How does tolerance work?** Absolute difference ≤ one cent/share is accepted, including the boundary. It is configurable and not a universal market standard.
7. **Exception record versus discrepancy?** One affected trade may contain several field findings; report both counts.
8. **How is indicative notional calculated?** Absolute gross quantity-times-price difference; missing records use available-side notional. Omit ambiguous or cross-currency cases.
9. **Why is it not P&L?** No marks, positions, fees, signed economic analysis, or validated cash movement. Equal gross values can hide significant breaks.
10. **What happens to malformed rows?** Retain values/errors and quarantine usable IDs on both sides. Blank IDs become separate row exceptions.
11. **How is match rate defined?** Fully reconciled IDs divided by all identifiable IDs. Explain the separate blank-ID count and denominator limitations.
12. **Why SQLite?** A local tool needs no database server. A concurrent team system would need stronger access and deployment controls.
13. **How do you prevent repeated imports?** Combine the internal snapshot hash and broker-file hash with source type and policy/version; enforce a unique fingerprint inside a transaction.
14. **What if a write fails midway?** Roll back the entire run. Tests inject invalid severity to verify no partial rows survive.
15. **Why resolution notes?** Explain why status changed for handoffs and review. Notes are not proof the source was corrected.
16. **How investigate a settlement break?** Inspect trade date, product conventions, calendars, confirmations, and amendments under applicable procedures; document evidence and escalate appropriately.
17. **How do you evaluate detection?** Unit tests isolate rules; independent injection ground truth checks exact detected/expected `(ID, type)` sets.
18. **Why deterministic generation?** Reproducible demos and failures. Seed plus fixed dates keeps results independent of the clock.
19. **How extend to options/ETFs?** Define identifiers, units, multipliers, lifecycle rules, source contracts, and acceptance tests before reusing equity logic.
20. **What is needed for production?** Product-aware matching/calendars, materiality, ownership, authentication, monitoring, migrations, retention, and realistic performance tests.

## Interview demo

Show a quantity/price break, explain the signed differences and absolute gross notional, add an investigation note, resolve, then reopen the same import to show preserved history. Run the ground-truth test. Finish with the shared-ID assumption, simple severity policy, and lack of connectivity. Report only observed test results; do not invent speed, savings, or production accuracy.

### Explain a single trade live

Choose **Single-trade walkthrough** in the sidebar. This uses the same database-backed pipeline with isolated scenario data, so you can demonstrate each rule without the 1,000-trade sample.

1. Submit WALK001 with BUY 100 shares at $10.00 on both sides. Explain the common trade ID and exact match.
2. Change broker quantity to 110 and submit. Explain: “The internal system records 100 shares; the broker confirms 110. I flag one exception with a quantity discrepancy of −10 shares, calculated as internal minus broker.”
3. Explain `abs(100 × 1000 − 110 × 1000) = 10,000 cents`: USD 100.00 is an indicative difference in recorded gross trade values, not profit or loss.
4. Move the exception to Investigating with a note. Resolve with a note explaining the simulated review. Resolving does not correct a real source record or change the original result.
5. Reset quantity to 100. Enter broker price 10.01, then 10.02. Explain the default inclusive one-cent tolerance.
6. Uncheck the broker side to demonstrate MISSING_BROKER. Alternatively, use different IDs and explain why the outer join produces two unmatched records.

Explain data flow: “The internal form simulates upstream capture into a local source database. The application reads that snapshot using SQL. The broker form supplies a fictional external confirmation through the existing CSV adapter in memory. I compare the two using the same engine as the portfolio, then retain results and status history in a separate walkthrough database.”

The form intentionally lets you edit inputs for teaching. It is not a real broker feed, execution system, or approval process. Use the saved-scenario selector to revisit earlier examples; editing the form alone does not change already saved results.
