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
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DB_PATH = Path("data/jobs.db")

TECH_ROLES = ["ai-ml", "data-science", "data-analytics", "data-eng", "it-infra"]

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


def where_clause(industries, roles, companies, open_only):
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
    if companies:
        parts.append(f"co.name IN ({','.join('?' * len(companies))})")
        params += companies
    return (" AND ".join(parts) or "1=1"), params


# ---------------------------------------------------------------- sidebar
if not DB_PATH.exists():
    st.error(f"{DB_PATH} not found. Run from the repo root.")
    st.stop()

meta = q("SELECT DISTINCT industry FROM companies ORDER BY 1")
all_companies = q("SELECT name FROM companies ORDER BY 1")
all_roles = q("SELECT DISTINCT role_category FROM postings ORDER BY 1")

st.sidebar.title("Filters")
page = st.sidebar.radio("View", ["Leaderboard", "Skill detail"], label_visibility="collapsed")
st.sidebar.divider()

sel_industries = st.sidebar.multiselect("Industry", meta["industry"].tolist())
sel_roles = st.sidebar.multiselect(
    "Role category", all_roles["role_category"].tolist(),
    default=[r for r in TECH_ROLES if r in all_roles["role_category"].tolist()],
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

WHERE, PARAMS = where_clause(sel_industries, sel_roles, sel_companies, open_only)

total_postings = q(
    f"""SELECT COUNT(*) n FROM postings p
        JOIN companies co ON co.id = p.company_id
        WHERE {WHERE}""", PARAMS
)["n"][0]

# ---------------------------------------------------------------- header
runs = q("SELECT MIN(run_date) a, MAX(run_date) b, COUNT(DISTINCT run_date) n FROM fetch_runs")
days = int(runs["n"][0] or 0)

c1, c2, c3 = st.columns(3)
c1.metric("Postings in scope", f"{total_postings:,}")
c2.metric("Days collected", days)
c3.metric("Closures observed", int(q("SELECT COUNT(*) n FROM postings WHERE closed_at IS NOT NULL")["n"][0]))

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
        width='stretch',
        height=min(760, 40 + 35 * len(df)),
        column_config={
            "skill": st.column_config.TextColumn("Skill", width="medium"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "postings": st.column_config.ProgressColumn(
                "Postings", format="%d", min_value=0,
                max_value=int(df["postings"].max()), width="large",
            ),
            "share": st.column_config.NumberColumn(
                "% of scope", format="%.1f%%", width="small",
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
            width='stretch',
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
            st.altair_chart(hbar(by_ind, "industry"), width='stretch')

        by_role = q(f"""SELECT p.role_category, COUNT(DISTINCT ps.posting_id) postings {base}
                        AND {SECTION_SQL} GROUP BY 1 ORDER BY 2 DESC""", P)
        if not by_role.empty:
            st.altair_chart(hbar(by_role, "role_category"), width='stretch')

    with right:
        st.subheader("Which companies")
        by_co = q(f"""SELECT co.name, COUNT(DISTINCT ps.posting_id) postings {base}
                      AND {SECTION_SQL} GROUP BY 1 ORDER BY 2 DESC""", P)
        st.dataframe(by_co, hide_index=True, width='stretch')

        st.subheader("Section split")
        by_sec = q(f"SELECT ps.section, COUNT(DISTINCT ps.posting_id) postings {base} GROUP BY 1", P)
        st.altair_chart(hbar(by_sec, "section"), width='stretch')

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
            st.altair_chart(hbar(co_occ, "skill", "together"), width='stretch')

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
                   CAST(julianday(COALESCE(p.closed_at, 'now')) - julianday(p.posted_at) AS INT) AS days
            {base} AND {SECTION_SQL} AND p.posted_at IS NOT NULL""", P
    )
    if age.empty:
        st.caption("No posted_at dates available yet.")
    else:
        st.bar_chart(age["days"].clip(upper=365).value_counts(bins=12).sort_index())
        st.caption(
            f"Median {int(age['days'].median())} days open. Capped at 365 for display. "
            "Long-lived postings are usually evergreen reqs, not active searches."
        )