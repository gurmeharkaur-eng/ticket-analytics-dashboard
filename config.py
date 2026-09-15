"""Constants shared across the ticket analytics engine and UI.

These mirror the definitions used in the reference Excel workbook
(Support_Ticket_Analytics_Dashboard.xlsx) exactly - do not change a boundary or
a status label here without also updating the Excel reference, since the two
are meant to produce identical numbers from the same raw data.
"""
from __future__ import annotations

APP_TITLE = "Support Ticket Analytics Dashboard"

# Backlog = currently open/unresolved work (case/whitespace-insensitive; both
# "Re-Opened" and "Reopened" spellings are recognized).
BACKLOG_STATUSES = {"OPEN", "NEW", "PENDING", "RE-OPENED", "REOPENED"}

# First Response / Resolution TAT buckets - upper bound inclusive, mutually
# exclusive, collectively exhaustive for any valid (non-negative) TAT value.
TAT_BUCKETS = ["<=1h", "1-4h", "4-8h", "8-16h", "16-20h", "20-24h", ">24h"]
TAT_BUCKET_BOUNDS = [1, 4, 8, 16, 20, 24]  # last bucket ">24h" is everything above

# Backlog ageing buckets - upper bound inclusive.
AGE_BUCKETS = ["0-1 Day", "1-3 Days", "3-7 Days", "7-14 Days", "14-30 Days", ">30 Days"]
AGE_BUCKET_BOUNDS = [1, 3, 7, 14, 30]

# Raw column names expected in the ticket export (Freshdesk-style). These are
# matched by NAME, not spreadsheet column letter, because column position
# shifts between exports (see Logic Validation).
COL_TICKET_ID = "Ticket ID"
COL_STATUS = "Status"
COL_TYPE = "Type"
COL_GROUP = "Group"
COL_CREATED = "Created time"
COL_RESOLVED = "Resolved time"
COL_INITIAL_RESPONSE = "Initial response time"
COL_SELLER_ID = "Seller ID"

REQUIRED_RAW_COLUMNS = [COL_TICKET_ID, COL_STATUS, COL_CREATED]
RECOMMENDED_RAW_COLUMNS = [COL_TYPE, COL_GROUP, COL_RESOLVED, COL_INITIAL_RESPONSE, COL_SELLER_ID]

MAP_SELLER_ID = "Seller ID"
MAP_SELLER_NAME = "Seller Name"
MAP_SALES_PERSON = "Sales Person Name"

# Number of trailing months shown in Month-on-Month tables, ending in the
# AS-OF month.
MOM_MONTHS_BACK = 12

# Groups (by ticket volume) used for "avoid small-sample TAT outliers" cuts,
# e.g. the "slowest Resolution TAT Group" insight only looks at the N largest
# Groups by volume.
TOP_N_FOR_TAT_OUTLIER_GUARD = 8

# --- Group / Type / Sales performance & actionable-insight mining ----------
# A segment (Group, Type, Group x Type combo, or Sales Person) needs at least
# this many tickets before its Resolution Rate / TAT is compared to benchmark
# - below this, deviations are noise, not signal.
MIN_SEGMENT_VOLUME = 20

# Resolution Rate = 1 - Backlog Rate, i.e. the share of a segment's tickets
# that are NOT currently stuck in backlog. This is the "conversion %"-style
# performance metric for a support-ticket context (higher = better handling).
# A segment is flagged when its Resolution Rate is this many percentage
# points below (underperform) or above (opportunity) the overall benchmark.
HIGH_PRIORITY_DEVIATION_PP = 0.10   # >=10pp worse -> High Priority problem
MEDIUM_PRIORITY_DEVIATION_PP = 0.05  # 5-10pp worse -> Medium Priority problem
OPPORTUNITY_DEVIATION_PP = 0.10     # >=10pp better -> Opportunity to replicate

# A segment's Avg Resolution TAT this much slower (relative) than benchmark
# also counts as a problem signal, independent of Resolution Rate.
TAT_DEVIATION_FLAG_PCT = 0.30

MAX_ACTIONABLE_INSIGHTS = 14

# "Performance Drivers" tables are curated, not exhaustive: show the top N
# segments by volume, unioned with any segment that's flagged even if it
# falls outside the top N (a real problem should never be hidden just
# because it's not top-volume). Full data stays available for reconciliation
# in Data Quality and for full detail in Detailed Data.
CURATED_TOP_N = 15

# --- TAT concentration diagnostics -----------------------------------------
# A segment is "disproportionately represented" in a slow-TAT bucket when its
# share of that bucket exceeds its share of overall volume by this multiple
# (e.g. 1.3x = 30% more of the slow bucket than its volume alone would predict).
TAT_CONCENTRATION_RATIO_FLAG = 1.3
# Minimum tickets a segment needs IN THE SLOW BUCKET before its concentration
# ratio is trusted (avoids a 2-ticket segment showing a wild ratio).
MIN_BUCKET_VOLUME_FOR_FLAG = 10
MAX_TAT_INSIGHTS = 12
