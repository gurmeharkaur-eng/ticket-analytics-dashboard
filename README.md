# Support Performance Report (code-based)

A single-page, no-tabs management report: upload your ticket export (+ seller
ownership files), get one scrollable report that answers what happened,
where the problem is, how big it is, what's driving it, and what to do next -
in about 2 minutes of reading.

## What's here

```
ticket_analytics_webapp/
  app.py                  # entry point - upload, orchestration
  config.py                # shared constants (buckets, thresholds, column names)
  src/
    ingestion.py           # load + validate all input files (CSV or XLSX)
    calculations.py        # per-ticket computed fields + seller ownership resolution
    aggregations.py        # grouped tables (Group/Type/Sales Person/Backlog/Ageing/TAT)
    performance.py          # benchmarking, quadrant classification, Group/Type/Sales insight mining
    seller_analysis.py      # Group x Type x Seller cut + seller-level insight mining
    tat_diagnostics.py      # TAT concentration analysis, ageing concentration, TAT insight mining
    logic_validation.py     # documentation of corrections made to the brief's assumed logic
    data_quality.py         # reconciliation checks
    styling.py               # compact CSS + small UI helpers
    report.py               # the single-page report layout - UI only, no business logic
  sample_data/              # local-only convenience defaults (gitignored - see below)
  requirements.txt
  .streamlit/config.toml
```

Business logic is fully separated from the UI: everything except `report.py`,
`styling.py` and `app.py` is plain pandas code with no Streamlit calls, so it
can be tested or reused independently of the report layout.

## Run it locally

```bash
cd ticket_analytics_webapp
pip install -r requirements.txt
streamlit run app.py
```

## Inputs

1. **Raw Ticket Export** (required) - CSV or XLSX.
2. **Sales Person Mapping** (required) - Seller ID -> Seller Name -> Sales
   Person. Can contain many repeated rows per seller; deduplicated
   automatically.
3. **Team Level Data** (optional, recommended) - `seller Id`, `Sales Person`,
   `Team`, `Owner`, `KAM Person`, `Month`. More complete and more current
   than the plain mapping file - **wins over it** wherever it covers a
   Seller ID (in this data: mapped-ticket coverage went from 27.5% to 73.5%
   once this file was added).
4. **Team Lists** (optional) - Sales Person -> Team roster. Fills in Team for
   a Sales Person that Team Level Data names but doesn't tag with a Team.

Replace any file any time - the whole report recalculates, including the
Executive Summary and every mined finding. No date, filename, row count or
person is hard-coded anywhere.

**`sample_data/` is entirely gitignored** - it holds local test copies of
all four input files (including real ticket/seller/rep data) purely for
convenience running the app locally. Nothing in it is ever pushed to GitHub
or shown to anyone who opens a deployed link; they'll see the upload prompt
until they supply their own files.

## Report structure (single page, no tabs)

1. **KPI strip** - Total Tickets, Backlog %, Resolution Rate, Avg Resolution
   TAT, Avg First Response TAT, % of tickets mapped to a seller owner.
2. **Executive Summary** - 🔴 Critical / 🟠 Attention / 🟡 Watch / 🟢 Healthy,
   drawn from one shared, impact-ranked pool of findings (see below) so the
   whole report tells one consistent story.
3. **Top 5 Problems** - the highest-impact findings across every cut,
   Group → Type → Seller → Metric → Problem style.
4. **Group → Type → Seller** - the core hierarchy. Curated: top Groups by
   volume (plus any flagged Group even if smaller), their top Types, and the
   Sellers driving each Type where volume is meaningful (≥20 tickets in that
   exact cell). Each row shows Sales Person + Team next to the Seller, and a
   🔴/🟢 flag against the overall benchmark.
5. **TAT Analysis** - Resolution TAT bucket distribution (≤1h ... >24h),
   long-TAT buckets highlighted.
6. **Seller Problem Table** - only sellers with meaningful volume, explicitly
   distinguishing **High-volume underperformer** (fix first) from
   **Low-volume outlier** (real, but limited impact today).
7. **Key Actions / Takeaways** - condensed from the same shared finding pool.
8. Collapsed at the bottom (still there, not competing for attention):
   Data Quality reconciliation, Logic Validation, and the full per-ticket
   detail table with CSV export.

### The shared finding pool

Every severity tier, the Top 5, and Key Actions all draw from **one**
impact-ranked list combining four sources: Group×Type performance, Sales
Rep performance (company-wide benchmark), Sales Rep-within-their-Group
performance (peer benchmark, catches individual outliers a company-wide
number would hide), and Seller performance (Group×Type×Seller cells). Impact
Score = tickets affected × |deviation from benchmark|, so a large,
meaningfully-underperforming segment always outranks a small one with a more
extreme percentage. Findings use hedged language ("pattern to investigate",
"potential driver") - the data proves the *what* and *how big*, never a
claimed root cause.

## Key business rules

- **Resolution Rate** = `1 - Backlog Rate` - the benchmarked performance
  metric used throughout (higher is better). A segment needs ≥20 tickets
  before it's compared to benchmark, to avoid small-sample noise.
- **First Response TAT** = `Initial response time - Created time`.
  **Resolution TAT** = `Resolved time - Created time`. Missing timestamps
  and negative values are excluded (not zeroed).
- **TAT buckets**: `≤1h, 1-4h, 4-8h, 8-16h, 16-20h, 20-24h, >24h` (upper
  bound inclusive).
- **Backlog** = `Open + New + Pending + Re-Opened` (case/whitespace-
  insensitive; `Reopened` also recognized).
- **Seller ownership resolution priority**: Team Level Data's Seller ID →
  Sales Person/Team wins where it covers a seller; the plain Sales Mapping
  file fills in Seller Name always, and Sales Person where Team Level Data
  doesn't cover that seller; Team Lists fills in Team for a Sales Person
  Team Level Data names but doesn't tag with a Team. See the report's
  Logic Validation section for the full list of corrections made and why.

## Verifying the numbers

Every figure was cross-checked against an independent pandas recomputation
during development. The collapsed Data Quality section runs the same
reconciliation checks live against whatever data you upload - every "Diff"
should read 0.
