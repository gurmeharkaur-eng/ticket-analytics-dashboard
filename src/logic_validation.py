"""Static documentation of corrections made to the brief's assumed logic
after inspecting the actual raw data - shown in the report's collapsed
'Logic Validation' section. This is pure documentation of decisions, not a
computed result, so it's fine to be a literal table rather than derived.
"""

LOGIC_VALIDATION_ROWS = [
    ("First Response TAT source columns",
     "Brief specifies Column P (Initial Response Time) minus Column I (Created Time).",
     "Column letters shift with export configuration - in a typical export, 'Initial response time' and "
     "'Created time' are not literally P and I.",
     "Matched by COLUMN NAME instead of letter: First Response TAT = 'Initial response time' - 'Created time'."),
    ("Resolution TAT source columns",
     "Brief specifies Column L (Resolved Time) minus Column I (Created Time).",
     "Same column-letter-drift issue as above.",
     "Matched by column NAME: Resolution TAT = 'Resolved time' - 'Created time'."),
    ("Raw pre-computed TAT (in hrs) columns",
     "These pre-computed columns look ready to use directly.",
     "They zero-fill tickets with no Initial Response / no Resolution instead of leaving them blank, and "
     "where a timestamp does exist the value often doesn't match simple elapsed time (likely a "
     "business-hours SLA calculation).",
     "TAT is recomputed directly from timestamps, excluding rows with a missing timestamp rather than "
     "trusting the pre-computed hour columns."),
    ("Negative TAT values",
     "Not addressed in raw data.",
     "A small number of tickets have a response/resolution timestamp earlier than the Created time "
     "(likely merged/relinked tickets).",
     "Negative TAT values are excluded from TAT calculations and bucket distributions (treated as missing, "
     "not as zero)."),
    ("TAT buckets",
     "An earlier formula reference used 5 buckets: <=1h, >1-4h, >4-24h, >24-72h, >72h.",
     "This brief specifies a different, more granular 7-bucket scheme.",
     "Uses the 7 buckets specified in this brief: <=1h, 1-4h, 4-8h, 8-16h, 16-20h, 20-24h, >24h "
     "(mutually exclusive, upper-bound inclusive)."),
    ("Group -> Type hierarchy",
     "Brief assumes Type is a clean subset of a single Group (each Type belongs to exactly one Group).",
     "In the raw data, most Types occur under more than one Group (e.g. 'Tech Queries' can appear under "
     "10+ different Groups) - Type is a general issue classification shared across teams, not "
     "Group-exclusive.",
     "The Group -> Type table is built on Group x Type COMBINATIONS rather than assuming one parent "
     "Group per Type, keeping roll-ups exact. Type Analysis additionally shows each Type's single "
     "largest-contributing 'Primary Group' for context."),
    ("Sales Person name casing",
     "Mapping sheet's 'Sales Person Name' values were assumed clean.",
     "The same person can appear under multiple casings (e.g. 'Pankaj Pareek' / 'pankaj Pareek'), which "
     "would fragment one person's workload into two rows.",
     "Names are normalized to title case (trimmed) during mapping cleanup so each person is counted once."),
    ("Sales mapping file size",
     "Uploaded mapping file treated as a simple lookup table.",
     "The file can contain many repeated rows for the same seller (a large historical export).",
     "Deduplicated to one row per Seller ID (first non-null Sales Person Name kept) before use."),
    ("Backlog status matching",
     "Backlog = Open + New + Pending + Re-Opened, matched on exact status text.",
     "A future upload could contain trimming/casing variants (e.g. 'open ', 'Reopened') that would "
     "silently fall outside an exact-match set.",
     "Backlog matching is case- and whitespace-insensitive, and recognizes both 'Re-Opened' and "
     "'Reopened' as the same status."),
    ("Backlog ageing 'as of' date",
     "Brief implies a fixed reference date for ageing.",
     "A hardcoded date would go stale the moment new raw data is loaded.",
     "AS_OF_DATE is computed live as end-of-day of the latest Created time in the currently loaded raw "
     "data, so ageing recalculates correctly on every upload."),
    ("'Waiting on Customer' status",
     "Brief's backlog definition lists Open, New, Pending, Re-Opened only.",
     "Raw data can also contain a 'Waiting on Customer' status, which is active/unresolved but not in "
     "the requested backlog set.",
     "Kept out of Backlog totals per the brief's literal definition, but shown separately in the report "
     "so it isn't silently dropped from status reporting."),
    ("Seller ownership resolution (Sales Person / Team)",
     "A single Sales Mapping file (Seller ID -> Seller Name -> Sales Person) was the only ownership source.",
     "The Team Level Data file covers far more sellers (4,511 vs ~5,900 rows but concentrated on sellers "
     "that actually raised tickets) and is more current, but has no Seller Name column; Team Lists names "
     "a Sales Person's Team but not their sellers.",
     "Ownership is resolved with a priority order: Team Level Data's Seller ID -> Sales Person/Team wins "
     "where it covers a seller; the plain Sales Mapping file fills in Seller Name always and Sales Person "
     "where Team Level Data doesn't cover that seller; Team Lists fills in Team for a Sales Person Team "
     "Level Data names but doesn't tag with a Team. A Seller ID appearing more than once in Team Level "
     "Data (2 conflicts found) keeps the most recent month's assignment."),
    ("First Response / Resolution TAT and Sunday",
     "TAT was calculated as plain calendar-elapsed time between timestamps.",
     "Sunday is a non-working day - counting it against TAT penalizes a ticket for sitting over a day "
     "nobody is working, unrelated to actual team performance.",
     "TAT is now business-day elapsed time: Sunday is excluded entirely, on every day it touches the "
     "interval. A ticket CREATED on a Sunday has its clock start pushed to the following Monday "
     "00:00:00; any Sunday FULLY spanned between start and end has a full 24h removed; and if a ticket's "
     "response/resolution TIME ITSELF falls on a Sunday (the end of the interval), the hours from that "
     "Sunday's midnight up to the actual response/resolution time are removed too - not just fully "
     "spanned Sundays. This applies to First Response TAT and Resolution TAT everywhere they're used "
     "(buckets, averages, medians, benchmarks). Backlog Age (how long a ticket has been waiting) is "
     "unaffected and stays pure calendar time - that's about elapsed wait, not work capacity."),
    ("Resolved In TAT % / Resolved Out of TAT %",
     "Not previously computed - the brief's TAT buckets used a flat 24h cutoff as a proxy for 'slow'.",
     "The raw 'Due by Time' column is 99.4% populated and is each ticket's actual per-ticket SLA deadline "
     "(varies by ticket, not a flat 24h rule). Cross-checked `Resolved time <= Due by Time` against the "
     "raw 'Resolution status' field (Within SLA / SLA Violated) on 7,297 tickets with both timestamps "
     "present: 100% agreement.",
     "Resolved In TAT % = share of resolved tickets where Resolved time <= Due by Time (computed directly "
     "from timestamps, not read off the raw status field, so it stays correct if Due by Time is edited or "
     "the export format changes). Tickets not yet resolved, or missing a Due by Time, are excluded, not "
     "counted as a breach."),
    ("Seller Name / Seller Company Name coverage",
     "Seller Name came only from the Sales Mapping file, which names just ~35% of ticket volume's sellers "
     "(868 of 1,714 unique Seller IDs in the sample) - the rest showed as a bare 'Seller <ID>'.",
     "An optional LSQ Seller Data file (e.g. a CRM/lead export) covers a largely different set of Seller "
     "IDs (294 new IDs beyond the mapping file, in the sample) and also carries a Seller Company Name "
     "field the mapping file doesn't have at all.",
     "Seller Name: Sales Mapping file's name first, LSQ Seller Data's name as a fallback only where the "
     "mapping file has none for that Seller ID (raises ticket-row name coverage from ~36% to ~60% in the "
     "sample) - never overrides a name the mapping file already has. Seller Company Name is a separate "
     "field sourced from LSQ alone (no fallback exists), shown alongside Seller Name, not merged into it, "
     "since a seller's display name and its registered company name are different things."),
]
