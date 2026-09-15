# Support Performance Dashboard (code-based)

A single-page, no-tabs leadership dashboard built around a CEO/CRO -> HOD ->
L1 -> L2 hierarchy: an executive topline view, a Group-performance view for
HODs, a Type-performance view for L1 Group Heads, and a ticket-level action
queue view for L2 Type Owners - all on one continuously-scrolling page
driven by a Group/Type filter pair at the top (not separate tabs or
workbook/page sheets - the point is to move from high-level to detail by
scrolling and filtering, not by navigating to a different view). Sales
Person / Seller-level breakdowns are intentionally not part of this
hierarchy - the dashboard's scope is Group and Type performance only (see
"Why no Sales Person view" below).

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
    tat_analysis.py         # First Response / Resolution TAT distributions, breach counts,
                             # funnel, diagnostics, heatmap data, status labels, What Changed
    charts.py                # Plotly figure builders (distribution bar, heatmap, scatter, funnel, trend line)
    seller_analysis.py      # Group x Type x Seller cut (supplementary detail only)
    trend_matrix.py         # the D-1..M-3 time-period matrix engine + color-coding
    logic_validation.py     # documentation of corrections made to the brief's assumed logic
    data_quality.py         # reconciliation checks
    styling.py               # compact CSS + small UI helpers (KPI cards, bar rankings, matrix/row color)
    report.py               # the CEO/CRO -> HOD -> L1 -> L2 dashboard layout - UI only, no business logic
  sample_data/              # local-only convenience defaults (gitignored - see below)
  requirements.txt
  .streamlit/config.toml
```

Business logic is fully separated from the UI: everything except `report.py`,
`styling.py`, `charts.py` and `app.py` is plain pandas code with no
Streamlit calls (`charts.py` builds Plotly figures but renders nothing
itself - `report.py` is the only place that calls Streamlit).

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

1. **CEO/CRO - Executive Overview**: topline KPI cards (Total Tickets,
   Backlog %, Resolution Rate, Avg + Median First Response / Resolution
   TAT, Backlog >7 days, Unknown/blank Type rate, Re-Opened rate); a
   **What Changed?** table (W-1 vs W-2, every headline metric with
   Previous/Current/Change/%Change/Interpretation, row-colored, or
   "Baseline not available" if a period has no data); a short **Needs
   Attention** list (top flagged segments - Groups when unfiltered, Types
   once a Group is selected); an **Executive Problem Statement** table
   (top quantified Group x Type risks, with a separate small table for
   real-but-low-volume outliers, never mixed into the main ranking); a
   **Top 5 Only** panel (Types by volume / backlog / median Resolution TAT
   / >72h breach - full detail lives in HOD/L1 below, not here); a compact
   horizontal-bar Resolution Rate ranking across all Groups; and the full
   D-1..M-3 Overall Performance trend matrix, collapsed by default.
2. **End-to-End TAT Funnel**: ticket counts and conversion % through
   raised -> valid First Response -> valid Resolution -> resolved <=24h /
   <=72h -> still-unresolved backlog, so timestamp completeness and
   resolution performance are visible in one chart.
3. **First Response TAT** and **Resolution TAT** (two mirrored, fully
   separate sections - a fast acknowledgement is not a fast resolution, so
   they're never shown as two columns of one crowded table): Avg/Median/
   valid-count/threshold-% KPI cards, each with a one-line plain-language
   definition and a live data-confidence caption (coverage % and a
   High/Moderate/Low label); the Group and Type with the highest
   *meaningful* median TAT (>=30 valid tickets), tagged with a status badge
   (Critical/Action Required/Watch/On Track/Low Sample - Validate/No
   Baseline Available); a 7-bucket distribution bar; breach-threshold
   cards (each expandable into the exact ticket list breaching it); a
   monthly trend line (M-3..MTD, breaks rather than draws through a period
   with <10 valid tickets); a Group x Type median-TAT heatmap (low-sample
   cells marked `*`); and Average-vs-Median / Volume-vs-TAT diagnostic
   scatter charts, toggleable between Group and Type.
4. **Backlog Risk**: Open/New/Pending/Re-Opened composition, a backlog
   ageing distribution bar, the oldest unresolved ticket, and a drill-down
   to the 30 oldest - kept explicitly separate from the TAT sections above,
   which only describe tickets that have already been responded to or
   resolved.
5. **HOD - Group Performance**: best/worst Groups, the full Group ranking
   table (Volume, status split, Resolution Rate, Avg+Median TAT, aged
   backlog, priority flag - every Group, row-colored), a collapsed trend
   matrix, and a collapsed Group-level First Response / Resolution TAT
   bucket control table.
6. **L1 - Group Performance & TAT Control**: the same shape as HOD, one
   level down (Type instead of Group) - scoped to the selected Group, or
   company-wide if unfiltered.
7. **Observed Patterns Associated with High TAT**: status mix,
   attribution/mapping coverage, and timestamp completeness for the
   current selection - titled to make clear these are measurable
   correlates, not confirmed causes.
8. **L2 - Type Owner: Ticket-Level Action Queues**: five live, sorted
   ticket-list queues (Immediate Response, Ageing, Resolution Escalation,
   Re-open Review, Classification), each with a real-time count and an
   expandable drill-down - no invented Owner/Due-date fields, since
   there's no source data for who's assigned or when something's due.
9. **Priority Actions** - Group x Type findings mined from the current
   selection, ranked by business impact (volume affected x performance gap
   vs benchmark).
10. Collapsed at the bottom: Data Quality reconciliation, a supplementary
    Seller Detail table (see below), Logic Validation, full per-ticket
    detail with CSV export.

### Why no Sales Person / Seller view

An earlier version of this dashboard included a Group -> Type -> Sales
Person drill-down and a Seller Performance / Seller Problem table as
first-class sections. Per a post-review redesign, Sales Person-level
bifurcation was removed from the leadership view entirely - the dashboard's
job is to answer "which Groups and Types need attention," not "which rep is
underperforming." The seller-level calculation (`seller_analysis.py`,
Seller Name / Seller Company Name resolution) is still fully computed and
available in the collapsed **Seller Detail** section for anyone who needs
it, just not part of the CEO/CRO -> HOD -> L1 -> L2 narrative.

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

### Status labels

Every "highest meaningful TAT" callout carries one of six restrained status
labels instead of a bare number: **Critical** (high volume + high backlog
rate + TAT materially above benchmark), **Action Required** (high backlog
rate OR TAT materially above benchmark), **Watch** (moderate backlog rate
or TAT deviation), **On Track**, **Low Sample - Validate** (fewer than 30
valid TAT tickets, or fewer than 20 tickets total - nothing else is
trustworthy below this floor), and **No Baseline Available** (the
benchmark itself couldn't be computed). Low Sample always takes priority
over every other label.

## Key business rules

- **Business-day TAT**: Sunday is excluded from First Response TAT and
  Resolution TAT everywhere (rankings, medians, benchmarks, trend matrices,
  distributions, heatmaps), on every day it touches the interval. A ticket
  created on a Sunday has its clock start pushed to the following Monday
  00:00:00; any Sunday *fully spanned* between start and end has a full
  24h removed; and if the response/resolution itself happens *on* a
  Sunday, the hours from that Sunday's midnight up to the actual
  response/resolution time are excluded too, not just fully-spanned
  Sundays. Backlog Age (how long a ticket has been *waiting*) is
  unaffected and stays pure calendar time.
- **Resolved In TAT %** = share of resolved tickets where
  `Resolved time <= Due by Time` (the ticket's own per-ticket SLA deadline,
  not a flat cutoff) - verified against the raw `Resolution status` field
  with 100% agreement on 7,297 tickets.
- **Resolution Rate** = `1 - Backlog Rate`, the benchmarked "conversion %"
  metric used for Group/Type flagging and ranking. A segment needs >=20
  tickets before it's compared to benchmark for Resolution Rate purposes;
  TAT-specific views (heatmap cells, diagnostic bubbles, the "highest
  meaningful TAT" callout) use a stricter 30-valid-TAT-ticket floor, since
  a single extreme ticket swings an average far more than it swings a
  backlog rate.
- **Backlog** = `Open + New + Pending + Re-Opened` (case/whitespace-
  insensitive; `Reopened` also recognized).
- **Filter scoping**: the Group/Type picker changes WHICH tickets feed the
  KPIs, ranking tables, and TAT sections, but never changes the benchmark
  itself - so narrowing to one Group doesn't make that Group trivially
  "average."
- **Missing timestamps are excluded, never zeroed**: every TAT KPI states
  its own valid-ticket count and coverage % (e.g. "7,288/10,039, 72.6%,
  confidence: moderate") rather than silently computing an average over a
  population that includes unresponded/unresolved tickets as if they were
  instant.
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
