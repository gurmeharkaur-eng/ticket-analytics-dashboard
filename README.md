# Support Performance Dashboard (code-based)

A single-page, no-tabs leadership dashboard built around a CRO -> HOD -> L1
hierarchy: an executive topline view, a Group-performance view for HODs, and
a Type-performance view for L1s, all on one continuously-scrolling page
driven by a Group/Type filter pair at the top. Sales Person / Seller-level
breakdowns are intentionally not part of this hierarchy - the dashboard's
scope is Group and Type performance only (see "Why no Sales Person view"
below).

## What's here

```
ticket_analytics_webapp/
  app.py                  # entry point - upload, orchestration
  config.py                # shared constants (buckets, thresholds, column names)
  src/
    ingestion.py           # load + validate all input files (CSV or XLSX)
    calculations.py        # per-ticket computed fields, business-day TAT, seller ownership
    aggregations.py        # grouped tables (Group/Type/Sales Person/Backlog/Ageing/TAT)
    performance.py          # benchmarking, Group/Type ranking, Priority Actions mining
    seller_analysis.py      # Group x Type x Seller cut (supplementary detail only)
    trend_matrix.py         # the D-1..M-3 time-period matrix engine + color-coding
    logic_validation.py     # documentation of corrections made to the brief's assumed logic
    data_quality.py         # reconciliation checks
    styling.py               # compact CSS + small UI helpers (KPI cards, bar rankings, matrix/row color)
    report.py               # the CRO -> HOD -> L1 dashboard layout - UI only, no business logic
  sample_data/              # local-only convenience defaults (gitignored - see below)
  requirements.txt
  .streamlit/config.toml
```

Business logic is fully separated from the UI: everything except `report.py`,
`styling.py` and `app.py` is plain pandas code with no Streamlit calls.

## Run it locally

```bash
cd ticket_analytics_webapp
pip install -r requirements.txt
streamlit run app.py
```

## Inputs

1. **Raw Ticket Export** (required) - CSV or XLSX.
2. **Sales Person Mapping** (required) - Seller ID -> Seller Name -> Sales Person.
3. **Team Level Data** (optional, recommended) - `seller Id`, `Sales Person`,
   `Team`, `Owner`, `KAM Person`, `Month`. Wins over the plain mapping file
   wherever it covers a Seller ID.
4. **Team Lists** (optional) - Sales Person -> Team roster, fills gaps Team
   Level Data leaves.
5. **LSQ Seller Data** (optional) - `Seller_ID`, `Seller_Name`,
   `Seller_Company_Name` (e.g. a CRM/lead export). Fills Seller Name gaps
   the Sales Mapping file doesn't cover, and is the only source for Seller
   Company Name. (Seller-level fields feed only the supplementary "Seller
   Detail" section at the bottom - see below.)

`sample_data/` is entirely gitignored - local test copies only, never
pushed to GitHub or shown on a deployed link.

## Dashboard structure (single page, no tabs)

**Filters** - a Group dropdown ("All Groups" by default) and a Type
dropdown that dynamically repopulates with only the Types belonging to the
selected Group. The filter scopes every section below it: leave both at
"All" for the company-wide view, pick a Group to focus everything on it,
then a Type to focus further. What does NOT move with the filter is the
benchmark every segment is compared against - that's always computed from
the full unfiltered upload, so "+5pp vs benchmark" means the same thing
whether or not you've drilled in.

1. **CRO - Executive Overview** (always the top, always the highest level):
   topline KPI cards (Total Tickets, Backlog %, Resolution Rate, Median
   First Response / Resolution TAT) for the current selection; a
   this-week-vs-last-week movement indicator for Resolution Rate and
   Backlog %; a short "Needs Attention" list (the 2-3 most business-impactful
   flagged segments - Groups when unfiltered, Types once a Group is
   selected); a compact horizontal-bar Resolution Rate ranking across all
   Groups; and the full D-1..M-3 Overall Performance trend matrix, collapsed
   by default.
2. **HOD - Group Performance**: best- and worst-performing Groups by
   Resolution Rate vs benchmark, then the full Group ranking table
   (Volume, Resolution Rate, deviation, Median TAT, priority flag - every
   Group, row-colored red/amber/green), with a collapsed D-1..M-3 trend
   matrix per Group underneath.
3. **L1 - Type Performance**: the same shape as HOD, one level down - best/
   worst Types, the full Type ranking table, and a collapsed Type trend
   matrix - scoped to the selected Group if one is chosen, or across the
   whole company otherwise.
4. **Priority Actions** - Group x Type findings mined from the current
   selection, ranked by business impact (volume affected x performance gap
   vs benchmark).
5. Collapsed at the bottom: Data Quality reconciliation, a supplementary
   Seller Detail table (see below), Logic Validation, full per-ticket detail
   with CSV export.

### Why no Sales Person / Seller view

An earlier version of this dashboard included a Group -> Type -> Sales
Person drill-down and a Seller Performance / Seller Problem table as
first-class sections. Per a post-review redesign, Sales Person-level
bifurcation was removed from the leadership view entirely - the dashboard's
job is to answer "which Groups and Types need attention," not "which rep is
underperforming." The seller-level calculation (`seller_analysis.py`,
Seller Name / Seller Company Name resolution) is still fully computed and
available in the collapsed **Seller Detail** section for anyone who needs
it, just not part of the CRO/HOD/L1 narrative.

### Color rule

Every colored cell/row is judged against the same full-period, full-company
benchmark and the same thresholds used throughout the app (>=10pp deviation
= red/dark opportunity, >=5pp = amber, >=10pp better = green). **D-1 and
D-2 are deliberately left uncolored** on rate/TAT cells in the trend
matrices: most of "today" and "yesterday"'s tickets haven't had time to
resolve yet, so Resolution Rate reads artificially low and the TAT of the
few already-resolved ones reads artificially fast (survivorship bias) -
neither is a fair performance read yet. Raw counts (Volume, Backlog#)
aren't subject to this and stay normally colored.

## Key business rules

- **Business-day TAT**: Sunday is excluded from First Response TAT and
  Resolution TAT everywhere (rankings, medians, benchmarks, trend matrices),
  on every day it touches the interval. A ticket created on a Sunday has its
  clock start pushed to the following Monday 00:00:00; any Sunday *fully
  spanned* between start and end has a full 24h removed; and if the
  response/resolution itself happens *on* a Sunday, the hours from that
  Sunday's midnight up to the actual response/resolution time are excluded
  too, not just fully-spanned Sundays. Backlog Age (how long a ticket has
  been *waiting*) is unaffected and stays pure calendar time.
- **Resolved In TAT %** = share of resolved tickets where
  `Resolved time <= Due by Time` (the ticket's own per-ticket SLA deadline,
  not a flat cutoff) - verified against the raw `Resolution status` field
  with 100% agreement on 7,297 tickets.
- **Resolution Rate** = `1 - Backlog Rate`, the benchmarked "conversion %"
  metric used for Group/Type flagging and ranking. A segment needs >=20
  tickets before it's compared to benchmark.
- **Backlog** = `Open + New + Pending + Re-Opened` (case/whitespace-
  insensitive; `Reopened` also recognized).
- **Filter scoping**: the Group/Type picker changes WHICH tickets feed the
  KPIs and ranking tables, but never changes the benchmark itself - so
  narrowing to one Group doesn't make that Group trivially "average."
- **Seller ownership resolution priority** (feeds the Data Quality and
  Seller Detail sections only): Team Level Data's Seller ID -> Sales
  Person/Team wins where it covers a seller; the plain Sales Mapping file
  fills in Seller Name always, and Sales Person where Team Level Data
  doesn't cover that seller; Team Lists fills in Team where Team Level Data
  names a Sales Person but doesn't tag a Team. Seller Name falls back to
  the optional LSQ Seller Data file only where the Sales Mapping file has
  none; Seller Company Name comes from LSQ alone. Full list of corrections
  and why: see the report's Logic Validation section.

## Verifying the numbers

Every figure was cross-checked against an independent pandas recomputation
during development, including hand-constructed test cases for the
Sunday-exclusion TAT logic. The collapsed Data Quality section runs the
same reconciliation checks live against whatever data you upload (scoped to
the current filter selection) - every "Diff" should read 0.
