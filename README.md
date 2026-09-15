# Support Ticket Analytics Dashboard (code-based)

A code-based recreation of the reference Excel workbook
(`ticket_dashboard/Support_Ticket_Analytics_Dashboard.xlsx`) as a runnable
Streamlit web app. Same KPIs, same calculations, same buckets, same tables,
same hierarchy, same Executive Summary logic, same Actionable Items logic -
the Excel workbook is kept only as the reference/source of truth; this app is
the product.

## What's here

```
ticket_analytics_webapp/
  app.py                  # entry point - upload, orchestration, tabs
  config.py                # shared constants (TAT/ageing buckets, backlog statuses, ...)
  src/
    ingestion.py           # load + validate the two input files (CSV or XLSX)
    calculations.py        # per-ticket computed fields (the "Computed" sheet, in code)
    aggregations.py        # every grouped table (Group/Type/Sales Person/Backlog/Ageing/TAT)
    performance.py          # benchmarking, quadrant classification, Group/Type/Sales insight mining
    tat_diagnostics.py      # TAT concentration analysis, ageing concentration, TAT insight mining
    insights.py             # Executive Summary key figures, narrative, Actionable Items
    data_quality.py         # reconciliation checks
    styling.py               # compact CSS + small UI helpers
    dashboard.py            # one render_*() function per tab - UI only, no business logic
  sample_data/              # the same two files used to build the reference Excel workbook
  requirements.txt
  .streamlit/config.toml
```

Business logic is fully separated from the UI: everything in `src/calculations.py`,
`src/aggregations.py`, `src/insights.py` and `src/data_quality.py` is plain
pandas code with no Streamlit calls, so it can be tested or reused independently
of the dashboard. `src/dashboard.py` and `app.py` only format and lay out the
DataFrames those modules produce.

## Run it locally

```bash
cd ticket_analytics_webapp
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`). The app
loads the sample data automatically on first run; upload your own files in
the sidebar to replace it - every KPI, table and the Executive Summary
recalculate immediately.

## Inputs

1. **Raw Ticket Export** (required) - CSV or XLSX. Needs at least `Ticket ID`,
   `Status`, `Created time`; also uses `Type`, `Group`, `Resolved time`,
   `Initial response time`, `Seller ID` when present (matched by column
   **name**, not position - see the Logic Validation tab).
2. **Sales Person Mapping** (required) - CSV or XLSX with `Seller ID`,
   `Seller Name`, `Sales Person Name`. Can contain many repeated rows per
   seller (a raw historical export); it's deduplicated automatically.

Replace either file any time - the whole dashboard, including the Executive
Summary narrative and Actionable Items, recalculates from the new data. No
date, filename, row count or person is hard-coded anywhere in the code.

## Tabs

Executive Summary -> Overall Analysis -> **Performance Drivers & Actions** ->
Backlog & Ageing -> **TAT Diagnostics** -> Data Quality -> Logic Validation ->
Detailed Data (per-ticket computed data, filterable, with CSV export - the
code equivalent of the Excel workbook's Computed/Raw Data tabs).

**Performance Drivers & Actions** merges Group, Type and Sales Person analysis
into one decision-support view, curated (not exhaustive) so it stays scannable:

1. *Management Focus* - the top 5 issues/opportunities across all three cuts,
   as Finding -> Evidence -> Impact -> Action cards, ranked by business impact
   (volume affected x deviation from benchmark) - not the most extreme %.
2. *Performance Snapshot* - overall benchmark KPIs plus best/worst Group,
   best/worst Type, best Sales Rep, and the single biggest underperforming
   segment.
3. *Performance Drivers* - the full Group roll-up, plus **curated**
   Group x Type and Sales Performance tables (top segments by volume, union
   any segment flagged for a meaningful deviation even if smaller - a real
   problem is never hidden for being small). Full, exhaustive tables still
   back the Data Quality reconciliation and the Detailed Data tab.
4. *Rep Performance Within Their Primary Group* - compares each rep only to
   peers working their own largest Group, not the company-wide benchmark.
5. *Opportunity & Problem Segments* - every qualifying segment classified into
   a volume x performance quadrant (High Priority / Best Practice-Scale /
   Potential Opportunity / Low Priority), across both Group x Type and Sales
   Rep cuts together.
6. *Priority Actions* - the full mined, prioritized list backing Management
   Focus above, as a compact table.

**TAT Diagnostics** goes beyond a bucket-distribution report to ask where
delay is concentrated, how severe it is, and what's driving it:

1. *Management Focus* - top 5 TAT problems as cards.
2. *TAT Snapshot* - avg/median First Response & Resolution TAT, %>24h.
3. *Where TAT is Concentrated* - **Concentration Ratio** = a segment's share
   of >24h tickets divided by its share of overall volume. Surfaces both
   segments disproportionately overrepresented in the slow bucket (ratio
   >=1.3x) AND the single largest absolute source of delay even when it's
   not disproportionate (e.g. a segment that's simply huge everywhere,
   including the slow bucket - still the highest-leverage fix available).
4. Full 7-bucket x Group/Type detail is kept, but tucked into a collapsible
   expander so it doesn't crowd the diagnostic view.
5. *TAT Drivers & Actions* - mined findings covering disproportionate >24h
   concentration, aged-backlog concentration (adaptive: falls back to >7
   days if no backlog has reached >14 days yet), and reps with unusually
   slow average Resolution TAT.

Both mined-insight lists use cautious, non-causal language ("pattern to
investigate", "potential driver") - the data proves the *what* and *how big*,
never a claimed root cause.

## Key business rules (unchanged from the Excel reference)

- **First Response TAT** = `Initial response time - Created time` (hours).
  **Resolution TAT** = `Resolved time - Created time` (hours). Missing
  timestamps and negative values are excluded (not zeroed).
- **TAT buckets**: `<=1h, 1-4h, 4-8h, 8-16h, 16-20h, 20-24h, >24h` (upper
  bound inclusive).
- **Backlog** = `Open + New + Pending + Re-Opened` (case/whitespace-insensitive;
  `Reopened` also recognized). `Waiting on Customer` is tracked separately,
  not counted in Backlog, per the brief's literal definition.
- **Ageing buckets**: `0-1 Day, 1-3 Days, 3-7 Days, 7-14 Days, 14-30 Days,
  >30 Days` (upper bound inclusive), measured from a live `AS_OF_DATE` =
  end-of-day of the latest `Created time` in the loaded raw data (never a
  hardcoded date).
- **Group -> Type hierarchy**: built on Group x Type *combinations*, not on
  an assumed single parent Group per Type, because many Types occur under
  more than one Group in the real data (see Logic Validation tab for the
  full list of corrections made and why).
- **Sales Person mapping**: dedupe by Seller ID, name casing normalized
  (title case) so the same person isn't split across rows; a ticket with no
  Seller ID is "No Seller ID", a Seller ID not present in the mapping sheet
  is "Unmapped Seller", a mapped seller with no rep on file is "Unassigned Rep".

## Verifying the numbers

Every figure in this app was cross-checked against the reference Excel
workbook (and against an independent pandas recomputation) during
development - Total Tickets, Total Backlog, TAT averages/medians/bucket
distributions, Group/Type/Sales Person roll-ups, and ageing all reconcile
exactly. The Data Quality tab runs the same reconciliation checks live
against whatever data you upload.
