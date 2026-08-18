# Job Market Skills Dashboard

## What this is
Collects job postings from ATS APIs on a daily schedule, extracts and
normalizes skill mentions, and dashboards skill demand by industry over time.

The value is the TIME SERIES, not the snapshot. Any single-day "top skills"
list is trivial. Trends, deltas, and time-to-fill are the product.

## Hard rules
- NEVER scrape Indeed or LinkedIn. No headless browsers, no proxy rotation,
  no user-agent spoofing. Data comes from public ATS APIs and schema.org
  JobPosting markup only.
- Never insert into `skill_aliases` automatically. LLM suggestions go to a
  review file for a human to approve. Silent alias drift corrupts the series.
- Postings are append-only history. Never delete or overwrite a posting row.

## Sources
Unauthenticated JSON, no keys required:
- Greenhouse: GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
  No server-side filtering. Pull the whole board, filter locally.
- Lever: GET https://api.lever.co/v0/postings/{company}?mode=json
  Returns a `lists` array preserving description sections. Prefer Lever
  where available since section context improves extraction.
- Ashby: posting API, best compensation coverage.

Company board tokens live in `config/companies.yml`, each with a manually
assigned `industry`. There is no industry field in any ATS response.
Classification is ours and is per-company, never per-posting.

## Schema (SQLite, data/jobs.db)
companies       id, name, ats, board_token, industry, added_at
postings        id, company_id, ats_job_id, title, location, remote_type,
                department, description_text, salary_min, salary_max,
                apply_url, first_seen, last_seen, closed_at
skills          id, canonical_name, category
skill_aliases   alias, skill_id
posting_skills  posting_id, skill_id, section
daily_counts    snapshot_date, industry, skill_id, posting_count

## Delisting logic (critical, read before touching the fetcher)
A posting that disappears from a board has closed. This gives us time-to-fill,
which nobody else computes. Cannot be backfilled, so it must be right from day one.

Per run, per company:
1. Record whether the fetch SUCCEEDED. Track this explicitly.
2. On success: any open posting for that company whose ats_job_id is absent
   from the response gets closed_at = today.
3. On failure (timeout, non-200, empty response, parse error): change nothing
   for that company. Do not touch closed_at.

Step 3 is the whole thing. A single failed fetch treated as success writes a
mass fake closure event into the permanent record.

## Skill extraction
1. Dictionary match against skill_aliases. Case-insensitive, word boundaries.
2. Record which section the match came from (requirements / responsibilities /
   other). Requirements mentions are the signal; "About us" mentions are noise.
3. Short ambiguous tokens need guarded patterns, not bare word matching:
   R, Go, C, C#, SAS, dbt. Match "R" only near statistical context.
4. Unmatched capitalized tokens append to data/review_queue.csv for manual
   triage. Do not LLM every posting. It is slow, expensive, and inconsistent
   across runs, which destroys the time series.

## Salary
The structured field is sparse on Greenhouse and Lever. Fall back to regex on
description_text: pay transparency laws in CO, CA, NY, WA, and IL push ranges
into the body. Store which method found it.

## Conventions
- Python 3, stdlib + requests / pandas / streamlit. No scraping frameworks.
- Every fetcher returns the same normalized dict shape. Add sources by adding
  a fetcher, never by special-casing downstream code.
- All timestamps UTC, ISO 8601.
- Rate limit: 1 req/sec per host, retry with backoff, cap at 3 attempts.

## Commands
source .venv/bin/activate
python -m src.db.init          # create schema
python -m src.fetch.run        # daily collection
python -m src.rollup           # build daily_counts
streamlit run app/dashboard.py

## Status
Scaffold stage. Priority order: schema, Greenhouse fetcher, delisting logic,
skill dictionary, rollup, dashboard. Dashboard last, on purpose. Start
collecting before you start visualizing.

## Lever specifics
- Response is a bare JSON array, not {"jobs": [...]}. Branch on this.
- 200 with [] means an account with no public postings. Not an error,
  but never treat it as a delisting event.
- Use descriptionPlain / descriptionBodyPlain. Skip the HTML variants.
- `lists` gives pre-split sections, but headers are NOT standardized
  ("Who You Are", "Requirements", "Qualifications" all mean the same
  thing). Map headers to buckets by keyword, never by exact match.
- salaryRange is frequently null. Regex descriptionPlain as primary.
- categories.allLocations can hold several locations for one posting.

## Role classification
Every posting gets a role_category from src/normalize/roles.py.
Classify at INGEST, filter at QUERY. Never filter during fetch.
Store all postings including non-technical ones. Dashboard defaults
to ai-ml, data-science, data-analytics, data-eng, it-infra.

## Skill discovery (core mechanism, not an extra)
AI tooling turns over faster than any hand-written dictionary can
track. A static dictionary reports only tools I already knew about
and is structurally blind to new ones, which are the interesting ones.

- Log every unmatched capitalized token WITH A COUNT, not a flag
- data/review_queue.csv sorted by frequency, reviewed weekly
- skills table gets first_seen_date, so I can chart when a tool
  entered the market
- Still never auto-promote. I approve every alias.