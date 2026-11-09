# Data

**To run the app you need nothing from this page.** It uses `extract/`, which is committed.

`extract/` holds only the rows the app reads: patient ids, the eight diabetes-related condition
codes, and the HbA1c results, about 11,000 of 900,000 rows. Each row keeps its line number in the
full CSV, so evidence points at the source file. `make extract` rebuilds it.

The full CSVs are needed for `make agents`, and the app uses them when present. They go in
`synthea/csv/`, which is gitignored: `patients.csv`, `conditions.csv`, and `observations.csv`.
`make data-check` confirms they are the canonical population.

## Canonical population

The canonical files are the ones behind the first article, generated on 2026-09-18 with Synthea
build `d9d07a6` for Mississippi with 1,000 requested patients and 1,153 generated.
`synthea/generation_metadata.json` is that run's own record.

| patients | exact SNOMED 44054006 | mentions "type 2 diabetes" | mentions "diabet" | HbA1c >= 6.5 | 2 OR 4 | 2 AND 4 |
|---|---|---|---|---|---|---|
| 1,153 | 74 | 115 | 474 | 41 | 142 | 14 |

**This population cannot be regenerated from a command.** The run recorded seed
`1789766283574` (a timestamp, Synthea's default), not 42. Its reference time was also a default
with millisecond precision, while `-r` accepts only a date. Passing the recorded seed with
`-r 20260918 -e 20260918` gave 1,137 patients, not 1,153.

To set up from the canonical files, copy the three CSVs into `synthea/csv/` and run
`make data-check`.

## Regenerating a similar population

This is deterministic in the tested case, but it is a **different population** and
`make data-check` will fail on it. Requires JDK 17+ and `synthea-with-dependencies.jar`
(build `d9d07a6`).

```bash
java -jar synthea-with-dependencies.jar -p 1000 -s 42 -r 20260918 -e 20260918 \
    --exporter.csv.export true --exporter.fhir.export false Mississippi
cp output/csv/{patients,conditions,observations}.csv data/synthea/csv/
```

Two runs of this command produced the same counts:

| patients | exact SNOMED 44054006 | mentions "type 2 diabetes" | mentions "diabet" | HbA1c >= 6.5 | 2 OR 4 | 2 AND 4 |
|---|---|---|---|---|---|---|
| 1,146 | 75 | 94 | 462 | 47 | 128 | 13 |

`-r` and `-e` matter: both default to the current time, so leaving them out changes the output
from day to day.
