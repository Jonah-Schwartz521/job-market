"""Skill demand dashboard.

Skills are the spine: everything else is a lens on a skill.

Two rules this app must not break:
  - A skill can appear in several sections of one posting, so posting counts
    are always COUNT(DISTINCT posting_id). COUNT(*) would double-count.
  - salary_min/max are the WIDEST BAND across every range in the posting, so
    they are a ceiling on spread, not a point estimate. Labelled as such.

Run:  streamlit run app/dashboard.py
"""

import sqlite3
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# streamlit run puts app/ on sys.path, not the repo root, so src/ is not
# importable until we say so.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.paths import db_path  # noqa: E402

DB_PATH = db_path()

# Two different questions, deliberately two constants. They happen to hold
# the same value today; they are not the same decision and may diverge.
#
#   DEFAULT_ROLES    what the dashboard shows before anyone touches a filter.
#                    An editorial choice. Widening it moves "Postings in
#                    scope" and every chart on the Leaderboard and Skill
#                    detail pages, so it is not a free change.
#   EXTRACTION_ROLES where the dictionary is EXPECTED to find skills, used as
#                    the denominator for the no-skill rate. A QA choice.
#                    Widening it moves one column on Data health and nothing
#                    else. Add 'software' here if you want SWE postings held
#                    to the same extraction standard.
DEFAULT_ROLES = ["ai-ml", "data-science", "data-analytics", "data-eng", "it-infra"]
EXTRACTION_ROLES = ["ai-ml", "data-science", "data-analytics", "data-eng",
                    "it-infra", "software"]

st.set_page_config(page_title="Skill Demand", layout="wide")


@st.cache_resource
def get_conn():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)


@st.cache_data(ttl=300)
def q(sql, params=()):
    return pd.read_sql_query(sql, get_conn(), params=params)


def hbar(df, label, value="postings"):
    """Horizontal bar, sorted by value. st.bar_chart mis-scales these."""
    return alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X(f"{value}:Q", title=None),
        y=alt.Y(f"{label}:N", sort="-x", title=None),
        tooltip=[label, value],
    ).properties(height=max(90, 26 * len(df)))


def where_clause(industries, roles, companies, open_only, seniority=None):
    """Build a shared filter fragment plus its params."""
    parts, params = [], []
    if open_only:
        parts.append("p.closed_at IS NULL")
    if industries:
        parts.append(f"co.industry IN ({','.join('?' * len(industries))})")
        params += industries
    if roles:
        parts.append(f"p.role_category IN ({','.join('?' * len(roles))})")
        params += roles
    if seniority:
        parts.append(f"p.seniority IN ({','.join('?' * len(seniority))})")
        params += seniority
    if companies:
        parts.append(f"co.name IN ({','.join('?' * len(companies))})")
        params += companies
    return (" AND ".join(parts) or "1=1"), params


def scope_caption(open_only, roles, seniority, industries, companies, n_active):
    """Describe the filters that actually produced the headline count.

    Counterpart to where_clause(): the two have to move together. A hardcoded
    caption drifts from the number the moment anyone touches the sidebar.
    """
    def listed(xs, limit):
        xs = list(xs)
        if len(xs) <= limit:
            return ", ".join(xs)
        return f"{', '.join(xs[:limit])} +{len(xs) - limit} more"

    bits = ["open postings" if open_only else "postings, open and closed,"]
    bits.append(f"in {listed(roles, 5)}" if roles else "in every role category")
    if seniority:
        bits.append(f"at {listed(seniority, 3)} level")
    if companies:
        bits.append(f"at {listed(companies, 3)}")
    elif industries:
        bits.append(f"at {listed(industries, 3)} companies")
    else:
        bits.append(f"across all {n_active} companies")
    return " ".join(bits)


# ---------------------------------------------------------------- sidebar
if not DB_PATH.exists():
    st.error(f"{DB_PATH} not found. Run from the repo root.")
    st.stop()

meta = q("SELECT DISTINCT industry FROM companies ORDER BY 1")
all_companies = q("SELECT name FROM companies ORDER BY 1")
all_roles = q("SELECT DISTINCT role_category FROM postings ORDER BY 1")
all_seniority = q("SELECT DISTINCT seniority FROM postings ORDER BY 1")

# Which database this is, on every page. A prod snapshot and the dev copy
# look identical once they are rendered as charts.
db_rows = int(q("SELECT COUNT(*) n FROM postings")["n"][0])
st.sidebar.caption(f"Data source: **`{DB_PATH.name}`**  \n{db_rows:,} posting rows")
st.sidebar.divider()

st.sidebar.title("Filters")
page = st.sidebar.radio(
    "View", ["Leaderboard", "Skill detail", "Data health"],
    label_visibility="collapsed",
)
st.sidebar.divider()

sel_industries = st.sidebar.multiselect(
    "Company industry", meta["industry"].tolist(),
    help="The employer's sector, assigned per company. All are software "
         "companies: 'healthcare-it' means health-tech vendors, not hospitals.",
)
sel_roles = st.sidebar.multiselect(
    "Role category", all_roles["role_category"].tolist(),
    default=[r for r in DEFAULT_ROLES if r in all_roles["role_category"].tolist()],
    help="What the job is, derived from the title. Includes non-technical "
         "roles: sales, finance, legal, people.",
)
sel_seniority = st.sidebar.multiselect(
    "Seniority", all_seniority["seniority"].tolist(),
    help="Derived from the title. 'unspecified' means the title carried no "
         "level word, which is about half of all postings.",
)
sel_companies = st.sidebar.multiselect("Company", all_companies["name"].tolist())
section = st.sidebar.selectbox(
    "Section", ["requirements", "requirements + responsibilities", "any"],
    help="Requirements mentions are what a job demands. 'any' includes About Us boilerplate.",
)
open_only = st.sidebar.checkbox("Open postings only", value=True)

SECTION_SQL = {
    "requirements": "ps.section = 'requirements'",
    "requirements + responsibilities": "ps.section IN ('requirements','responsibilities')",
    "any": "1=1",
}[section]

WHERE, PARAMS = where_clause(
    sel_industries, sel_roles, sel_companies, open_only, sel_seniority
)

total_postings = q(
    f"""SELECT COUNT(*) n FROM postings p
        JOIN companies co ON co.id = p.company_id
        WHERE {WHERE}""", PARAMS
)["n"][0]

# ---------------------------------------------------------------- data health
if page == "Data health":
    st.header("Data health")
    st.caption(
        "This page ignores the sidebar filters on purpose: it describes the "
        "whole collection, not a slice of it."
    )

    span = q("""SELECT MIN(run_date) a, MAX(run_date) b,
                       COUNT(DISTINCT run_date) collected,
                       CAST(julianday(MAX(run_date)) - julianday(MIN(run_date)) AS INT) + 1 total
                FROM fetch_runs""")
    collected = int(span["collected"][0] or 0)
    total_days = int(span["total"][0] or 0)
    missed = max(0, total_days - collected)

    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Days collected", collected,
              f"-{missed} missed" if missed else None, delta_color="inverse",
              help="A gap inflates time-to-fill: a posting that closed during "
                   "the gap is stamped with the day collection resumed.")
    h2.metric("Calendar span", f"{total_days} d", f"{span['a'][0]} to {span['b'][0]}")
    h3.metric("Total postings", f"{int(q('SELECT COUNT(*) n FROM postings')['n'][0]):,}")
    h4.metric("Skill mentions", f"{int(q('SELECT COUNT(*) n FROM posting_skills')['n'][0]):,}")

    if missed:
        have = set(q("SELECT DISTINCT run_date d FROM fetch_runs")["d"])
        all_days = pd.date_range(span["a"][0], span["b"][0]).strftime("%Y-%m-%d")
        st.warning("No run on: " + ", ".join(d for d in all_days if d not in have))

    st.divider()
    st.subheader("Per company")

    # No-skill rate is an extraction-quality metric, so its denominator is
    # the technical roles only. Over all roles it measures a company's role
    # mix instead: a sales-heavy board reads ~50% while extracting perfectly.
    tech_ph = ",".join("?" * len(EXTRACTION_ROLES))
    health = q(f"""
        SELECT co.name AS company, co.ats, co.industry,
               COUNT(p.id) AS open_postings,
               SUM(p.salary_min IS NOT NULL) AS with_salary,
               SUM(p.role_category = 'other') AS role_other,
               SUM(CASE WHEN p.role_category IN ({tech_ph})
                        THEN 1 ELSE 0 END) AS tech_postings,
               SUM(CASE WHEN p.role_category IN ({tech_ph})
                         AND ps.posting_id IS NULL
                        THEN 1 ELSE 0 END) AS tech_no_skills,
               (SELECT MAX(run_date) FROM fetch_runs f
                 WHERE f.company_id = co.id AND f.status = 'success') AS last_ok,
               (SELECT COUNT(*) FROM fetch_runs f
                 WHERE f.company_id = co.id AND f.status = 'failed') AS failures
        FROM companies co
        LEFT JOIN postings p
               ON p.company_id = co.id AND p.closed_at IS NULL
        LEFT JOIN (SELECT DISTINCT posting_id FROM posting_skills) ps
               ON ps.posting_id = p.id
        WHERE co.active = 1
        GROUP BY co.id ORDER BY co.name
    """, EXTRACTION_ROLES * 2)

    latest = span["b"][0]
    health["stale"] = health["last_ok"] != latest
    # nan, not pd.NA: a company with no open technical postings divides by
    # zero here, and NAType has no __round__.
    open_n = health["open_postings"].replace(0, float("nan"))
    tech_n = health["tech_postings"].replace(0, float("nan"))
    for col, src in (("salary %", "with_salary"), ("other-role %", "role_other")):
        health[col] = (health[src] / open_n * 100).round(0)
    health["no-skill %"] = (health["tech_no_skills"] / tech_n * 100).round(0)

    st.dataframe(
        health[["company", "ats", "industry", "open_postings", "tech_postings",
                "salary %", "no-skill %", "other-role %", "failures", "last_ok",
                "stale"]],
        hide_index=True, width="stretch", height=min(760, 40 + 35 * len(health)),
        column_config={
            "open_postings": st.column_config.NumberColumn("Open"),
            "salary %": st.column_config.ProgressColumn(
                "Salary", format="%.0f%%", min_value=0, max_value=100,
                help="Share of open postings with a parsed salary range."),
            "tech_postings": st.column_config.NumberColumn(
                "Tech",
                help="Open postings in " + ", ".join(EXTRACTION_ROLES) + ". This is "
                     "the denominator for the No skills column."),
            "no-skill %": st.column_config.ProgressColumn(
                "No skills (tech)", format="%.0f%%", min_value=0, max_value=100,
                help="Of the Tech postings only, the share where the dictionary "
                     "matched nothing. Blank means the company has no open "
                     "postings in those categories. Read it against Tech: one "
                     "miss out of three is not a 33% extraction problem."),
            "other-role %": st.column_config.ProgressColumn(
                "Role 'other'", format="%.0f%%", min_value=0, max_value=100),
            "failures": st.column_config.NumberColumn("Fails"),
            "last_ok": st.column_config.TextColumn("Last OK"),
            "stale": st.column_config.CheckboxColumn(
                "Stale", help="No successful fetch on the most recent run date."),
        },
    )

    stale = health[health["stale"]]["company"].tolist()
    if stale:
        st.error("No successful fetch on the latest run date: " + ", ".join(stale))
    else:
        st.success("Every active company fetched successfully on the latest run.")

    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("Recent failures")
        fails = q("""SELECT f.run_date, co.name AS company, f.http_status, f.error
                     FROM fetch_runs f JOIN companies co ON co.id = f.company_id
                     WHERE f.status = 'failed'
                     ORDER BY f.run_date DESC, co.name LIMIT 25""")
        if fails.empty:
            st.caption("No failed fetches on record.")
        else:
            st.dataframe(fails, hide_index=True, width="stretch")

    with right:
        st.subheader("Coverage overall")
        cov = q("""
            SELECT
              (SELECT COUNT(*) FROM postings WHERE closed_at IS NULL) AS open_p,
              (SELECT COUNT(*) FROM postings WHERE closed_at IS NULL AND salary_min IS NOT NULL) AS sal,
              (SELECT COUNT(*) FROM postings WHERE closed_at IS NULL AND posted_at IS NOT NULL) AS posted,
              (SELECT COUNT(*) FROM postings WHERE closed_at IS NULL AND role_category != 'other') AS roled,
              (SELECT COUNT(*) FROM postings WHERE closed_at IS NULL AND seniority != 'unspecified') AS senior,
              (SELECT COUNT(DISTINCT posting_id) FROM posting_skills) AS skilled
        """)
        n = int(cov["open_p"][0]) or 1
        bars = pd.DataFrame({
            "field": ["salary", "posted_at", "role classified", "seniority known", "any skill"],
            "pct": [round(int(cov[c][0]) / n * 100, 1)
                    for c in ("sal", "posted", "roled", "senior", "skilled")],
        })
        st.altair_chart(
            alt.Chart(bars).mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("pct:Q", title="% of open postings", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("field:N", sort="-x", title=None),
                tooltip=["field", "pct"],
            ).properties(height=150), width="stretch")
        st.caption(
            "Low salary coverage is expected: only Ashby exposes a structured "
            "comp field, so everything else depends on pay-transparency text."
        )

    st.divider()
    st.subheader("Postings and closures by day")
    daily = q("""
        SELECT run_date AS day,
               (SELECT COUNT(*) FROM postings WHERE first_seen LIKE f.run_date || '%') AS new_postings,
               (SELECT COUNT(*) FROM postings WHERE closed_at = f.run_date) AS closed
        FROM (SELECT DISTINCT run_date FROM fetch_runs) f ORDER BY day
    """)
    st.dataframe(daily, hide_index=True, width="stretch")

    st.stop()

# ---------------------------------------------------------------- header
runs = q("SELECT MIN(run_date) a, MAX(run_date) b, COUNT(DISTINCT run_date) n FROM fetch_runs")
days = int(runs["n"][0] or 0)

c1, c2, c3 = st.columns(3)
c1.metric("Postings in scope", f"{total_postings:,}",
          help="Open postings matching the filters at left, not the whole database.")
c2.metric("Days collected", days)
c3.metric("Closures observed", int(q("SELECT COUNT(*) n FROM postings WHERE closed_at IS NOT NULL")["n"][0]))

n_co = int(q("SELECT COUNT(*) n FROM companies WHERE active=1")["n"][0])
st.caption(
    "Scope: " + scope_caption(
        open_only, sel_roles, sel_seniority, sel_industries, sel_companies, n_co
    ) + ". Those are software companies on Greenhouse, Lever, and Ashby, "
    "carrying every role they post, technical or not. No non-software "
    "employers: banks and hospitals use ATS platforms with no public API."
)

if days < 14:
    st.info(
        f"Collecting since {runs['a'][0]}. Trend and time-to-fill views need "
        f"a few weeks of history before they mean anything."
    )

if total_postings == 0:
    st.warning("No postings match these filters.")
    st.stop()

# ---------------------------------------------------------------- leaderboard
if page == "Leaderboard":
    st.header("Skill demand")

    df = q(
        f"""
        SELECT s.canonical_name AS skill, s.category,
               COUNT(DISTINCT ps.posting_id) AS postings
        FROM posting_skills ps
        JOIN skills s     ON s.id = ps.skill_id
        JOIN postings p   ON p.id = ps.posting_id
        JOIN companies co ON co.id = p.company_id
        WHERE {SECTION_SQL} AND {WHERE}
        GROUP BY 1, 2 ORDER BY postings DESC
        """, PARAMS
    )

    if df.empty:
        st.warning("No skill mentions match these filters.")
        st.stop()

    df["share"] = (df["postings"] / total_postings * 100).round(1)

    search = st.text_input(
        "Filter skills", placeholder="type to filter, e.g. kube",
        label_visibility="collapsed",
    )
    if search:
        df = df[df["skill"].str.contains(search, case=False, na=False)]
        if df.empty:
            st.warning(f"No skill matches '{search}'.")
            st.stop()

    cats = sorted(df["category"].unique())
    picked = st.pills("Category", cats, selection_mode="multi", default=None)
    if picked:
        df = df[df["category"].isin(picked)]

    st.dataframe(
        df[["skill", "category", "postings", "share"]],
        hide_index=True,
        width="stretch",
        height=min(760, 40 + 35 * len(df)),
        column_config={
            "skill": st.column_config.TextColumn("Skill", width="medium"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "postings": st.column_config.ProgressColumn(
                "Postings", format="%d", min_value=0,
                max_value=int(df["postings"].max()), width="large",
            ),
            "share": st.column_config.NumberColumn(
                "% of postings", format="%.1f%%", width="small",
                help="Share of the postings currently in scope that require "
                     "this skill. Changes as you change filters.",
            ),
        },
    )

    st.caption(
        f"{len(df)} skills across {total_postings:,} postings in scope. Counts are "
        "distinct postings, not mentions: a skill named three times in one "
        "posting counts once. Click a column header to re-sort."
    )

    by_cat = df.groupby("category", as_index=False)["postings"].sum()
    with st.expander(f"By category ({len(by_cat)})"):
        st.altair_chart(
            alt.Chart(by_cat).mark_bar(cornerRadiusEnd=3, height=18).encode(
                x=alt.X("postings:Q", title="postings"),
                y=alt.Y("category:N", sort="-x", title=None),
                tooltip=["category", "postings"],
            ).properties(height=28 * len(by_cat)),
            width="stretch",
        )

# ---------------------------------------------------------------- skill detail
else:
    available = q(
        f"""SELECT DISTINCT s.canonical_name AS skill
            FROM posting_skills ps
            JOIN skills s     ON s.id = ps.skill_id
            JOIN postings p   ON p.id = ps.posting_id
            JOIN companies co ON co.id = p.company_id
            WHERE {WHERE} ORDER BY 1""", PARAMS
    )["skill"].tolist()

    if not available:
        st.warning("No skills found under these filters.")
        st.stop()

    skill = st.selectbox("Skill", available)
    st.header(skill)

    base = f"""
        FROM posting_skills ps
        JOIN skills s     ON s.id = ps.skill_id
        JOIN postings p   ON p.id = ps.posting_id
        JOIN companies co ON co.id = p.company_id
        WHERE s.canonical_name = ? AND {WHERE}
    """
    P = [skill] + PARAMS

    n_req = q(f"SELECT COUNT(DISTINCT ps.posting_id) n {base} AND ps.section='requirements'", P)["n"][0]
    n_any = q(f"SELECT COUNT(DISTINCT ps.posting_id) n {base}", P)["n"][0]

    a, b, c = st.columns(3)
    a.metric("Postings requiring it", f"{n_req:,}", f"{n_req/total_postings*100:.1f}% of scope")
    b.metric("Postings mentioning it anywhere", f"{n_any:,}")
    c.metric("Gate rate", f"{(n_req/n_any*100 if n_any else 0):.0f}%",
             help="Share of mentions that sit in a requirements section. "
                  "High means it is a hard requirement, low means nice-to-have.")

    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("Where it is asked for")
        by_ind = q(f"""SELECT co.industry, COUNT(DISTINCT ps.posting_id) postings {base}
                       AND {SECTION_SQL} GROUP BY 1 ORDER BY 2 DESC""", P)
        if by_ind.empty:
            st.caption("none")
        else:
            st.altair_chart(hbar(by_ind, "industry"), width="stretch")

        by_role = q(f"""SELECT p.role_category, COUNT(DISTINCT ps.posting_id) postings {base}
                        AND {SECTION_SQL} GROUP BY 1 ORDER BY 2 DESC""", P)
        if not by_role.empty:
            st.altair_chart(hbar(by_role, "role_category"), width="stretch")

        by_sen = q(f"""SELECT p.seniority, COUNT(DISTINCT ps.posting_id) postings {base}
                       AND {SECTION_SQL} GROUP BY 1 ORDER BY 2 DESC""", P)
        if not by_sen.empty:
            st.altair_chart(hbar(by_sen, "seniority"), width="stretch")

    with right:
        st.subheader("Which companies")
        by_co = q(f"""SELECT co.name, COUNT(DISTINCT ps.posting_id) postings {base}
                      AND {SECTION_SQL} GROUP BY 1 ORDER BY 2 DESC""", P)
        st.dataframe(by_co, hide_index=True, width="stretch")

        st.subheader("Section split")
        by_sec = q(f"SELECT ps.section, COUNT(DISTINCT ps.posting_id) postings {base} GROUP BY 1", P)
        st.altair_chart(hbar(by_sec, "section"), width="stretch")

    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("Travels with")
        co_occ = q(
            f"""
            SELECT s2.canonical_name AS skill, COUNT(DISTINCT ps2.posting_id) AS together
            FROM posting_skills ps
            JOIN skills s     ON s.id = ps.skill_id
            JOIN postings p   ON p.id = ps.posting_id
            JOIN companies co ON co.id = p.company_id
            JOIN posting_skills ps2 ON ps2.posting_id = ps.posting_id
            JOIN skills s2    ON s2.id = ps2.skill_id
            WHERE s.canonical_name = ? AND s2.canonical_name != ?
              AND {SECTION_SQL} AND {WHERE}
            GROUP BY 1 ORDER BY together DESC LIMIT 12
            """, [skill, skill] + PARAMS
        )
        if co_occ.empty:
            st.caption("No co-occurring skills under these filters.")
        else:
            st.altair_chart(hbar(co_occ, "skill", "together"), width="stretch")

    with right:
        st.subheader("Posted salary")
        sal = q(
            f"""SELECT DISTINCT p.id, p.salary_min, p.salary_max {base}
                AND {SECTION_SQL} AND p.salary_min IS NOT NULL
                AND p.salary_period = 'year' AND p.salary_currency = 'USD'""", P
        )
        allsal = q(
            f"""SELECT p.salary_min, p.salary_max FROM postings p
                JOIN companies co ON co.id = p.company_id
                WHERE {WHERE} AND p.salary_min IS NOT NULL
                AND p.salary_period='year' AND p.salary_currency='USD'""", PARAMS
        )
        if sal.empty:
            st.caption("No USD annual ranges on postings requiring this skill yet.")
        else:
            mid = (sal["salary_min"] + sal["salary_max"]) / 2
            allmid = (allsal["salary_min"] + allsal["salary_max"]) / 2
            m1, m2 = st.columns(2)
            m1.metric(f"Median midpoint, {skill}", f"${mid.median():,.0f}", f"n={len(sal)}")
            m2.metric("Median midpoint, all in scope", f"${allmid.median():,.0f}", f"n={len(allsal)}")
            st.caption(
                "Stored ranges are the widest band across every range in a posting, "
                "so they overstate spread. Midpoints are more comparable than the edges."
            )

    st.divider()
    st.subheader("Posting age")
    age = q(
        f"""SELECT DISTINCT p.id,
                   CAST(julianday(date(COALESCE(p.closed_at, 'now')))
                        - julianday(date(p.posted_at)) AS INT) AS days
            {base} AND {SECTION_SQL} AND p.posted_at IS NOT NULL""", P
    )
    if age.empty:
        st.caption("No posted_at dates available yet.")
    else:
        # Explicit buckets: value_counts(bins=) yields an Interval index that
        # Streamlit renders as raw JSON and sorts alphabetically.
        EDGES = [0, 7, 14, 30, 60, 90, 180, 365, 10 ** 6]
        LABELS = ["<1w", "1-2w", "2-4w", "1-2m", "2-3m", "3-6m", "6-12m", "1y+"]
        buckets = pd.cut(age["days"].clip(lower=0), bins=EDGES, labels=LABELS, right=False)
        hist = buckets.value_counts().reindex(LABELS).reset_index()
        hist.columns = ["bucket", "postings"]

        st.altair_chart(
            alt.Chart(hist).mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("bucket:N", sort=LABELS, title="days open",
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("postings:Q", title=None),
                tooltip=["bucket", "postings"],
            ).properties(height=220),
            width="stretch",
        )
        st.caption(
            f"Median {int(age['days'].median())} days open. Long-lived postings "
            "are usually evergreen reqs, not active searches."
        )