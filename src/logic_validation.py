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
]
