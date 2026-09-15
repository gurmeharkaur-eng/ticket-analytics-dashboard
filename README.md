# Support Performance Report (code-based)

A single-page, no-tabs MIS report modeled on the team's own Freshdesk report
format (metrics/segments as rows, time periods as columns: D-1..D-7,
W-1..W-4, MTD, M-1..M-3), with red/amber/green color-coding layered on top
and our Group/Type/Sales Person/Seller cuts built in.

## What's here

```
ticket_analytics_webapp/
  app.py                  # entry point - upload, orchestration
  config.py                # shared constants (buckets, thresholds, column names)
  src/
    ingestion.py           # load + validate all input files (CSV or XLSX)
    calculations.py        # per-ticket computed fields, business-day TAT, seller ownership
    aggregations.py        # grouped tables (Group/Type/Sales Person/Backlog/Ageing/TAT)
    performance.py          # benchmarking, quadrant classification, Group/Type/Sales insight mining
    seller_analysis.py      # Group x Type x Seller cut + seller-level insight mining
    tat_diagnostics.py      # TAT concentration analysis, ageing concentration, TAT insight mining
    trend_matrix.py         # the D-1..M-3 time-period matrix engine + color-coding
    logic_validation.py     # documentation of corrections made to the brief's assumed logic
    data_quality.py         # reconciliation checks
    styling.py               # compact CSS + small UI helpers (incl. matrix/row color rendering)
    report.py               # the single-page report layout - UI only, no business logic
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
   wherever it covers a Seller ID (mapped-ticket coverage: 27.5% -> 73.5%
   with this file added).
4. **Team Lists** (optional) - Sales Person -> Team roster, fills gaps Team
   Level Data leaves.

`sample_data/` is entirely gitignored - local test copies only, never
pushed to GitHub or shown on a deployed link.

## Report structure (single page, no tabs)

1. **KPI strip** - Total Tickets, Backlog %, Resolution Rate, **Median**
   Resolution/First-Response TAT, % mapped to a seller owner.
2. **Color legend + data-coverage note** - which time periods the loaded
   data actually supports (periods with zero tickets show "-", never a
   misleading 0%/0-colored cell).
3. **Overall Performance matrix** - Total Tickets #, Backlog #/%,
   Resolved+Closed %, **Resolved In TAT % / Out of TAT %** (per-ticket,
   using the real Due-by-Time deadline - see below), Median Resolution/First
   Response TAT, each across D-1..M-3, color-coded against the full-period
   benchmark.
4. **Group → Type → Sales Person matrices (x2: First Response TAT and
   Resolution TAT)** - one nested table, not three disconnected cuts: Type
   is a subset of Group, and each Sales Person's work within a Group x Type
   is a further subset, so it's shown that way (indented rows), curated at
   each level (top Groups by volume, their top Types, the Sales Persons
   driving each). A rep's cell turning red/amber in a recent period after
   being green earlier is the signal to watch. Plus a **Seller matrix**
   (Volume + Resolution Rate, top sellers by volume).
5. **Seller Problem Table** - every Group x Type x Seller combination with
   >=20 tickets, **not filtered down to a shortlist** - the whole table,
   with the row itself colored (red/amber/green) so problems are scannable
   without hiding the rest of the data.
6. **Priority Actions** - mined findings from the current snapshot, ranked
   by business impact.
7. Collapsed at the bottom: Data Quality reconciliation, Logic Validation,
   full per-ticket detail with CSV export.

### Color rule

Every colored cell is judged against the same full-period benchmark and the
same thresholds used throughout the app (≥10pp deviation = red/dark
opportunity, ≥5pp = amber, ≥10pp better = green). **D-1 and D-2 are
deliberately left uncolored** on rate/TAT rows: most of "today" and
"yesterday"'s tickets haven't had time to resolve yet, so Resolution Rate
reads artificially low and the TAT of the few already-resolved ones reads
artificially fast (survivorship bias) - neither is a fair performance read
yet. Raw counts (Volume, Backlog#) aren't subject to this and stay normally
colored.

## Key business rules

- **Business-day TAT**: Sunday is excluded from First Response TAT and
  Resolution TAT everywhere (buckets, averages, medians, benchmarks). A
  ticket created on a Sunday has its clock start pushed to the following
  Monday 00:00:00; any Sunday a response/resolution window spans has a full
  24h removed. Backlog Age (how long a ticket has been *waiting*) is
  unaffected and stays pure calendar time.
- **Resolved In TAT %** = share of resolved tickets where
  `Resolved time <= Due by Time` (the ticket's own per-ticket SLA deadline,
  not a flat cutoff) - verified against the raw `Resolution status` field
  with 100% agreement on 7,297 tickets.
- **Resolution Rate** = `1 - Backlog Rate`, the benchmarked "conversion %"
  metric used for segment-level flagging. A segment needs ≥20 tickets before
  it's compared to benchmark.
- **Backlog** = `Open + New + Pending + Re-Opened` (case/whitespace-
  insensitive; `Reopened` also recognized).
- **Seller ownership resolution priority**: Team Level Data's Seller ID →
  Sales Person/Team wins where it covers a seller; the plain Sales Mapping
  file fills in Seller Name always, and Sales Person where Team Level Data
  doesn't cover that seller; Team Lists fills in Team where Team Level Data
  names a Sales Person but doesn't tag a Team. Full list of corrections and
  why: see the report's Logic Validation section.

## Verifying the numbers

Every figure was cross-checked against an independent pandas recomputation
during development, including hand-constructed test cases for the
Sunday-exclusion TAT logic. The collapsed Data Quality section runs the
same reconciliation checks live against whatever data you upload - every
"Diff" should read 0.
