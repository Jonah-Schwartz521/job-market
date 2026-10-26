# Final Project Proposal: Tool Stacks Across Data and AI Roles

**Jonah Schwartz** · INFO 4617 Web Data Science · Solo · Oct 25, 2026

## 1. Research question

**Among data analyst, data scientist, and AI/ML job postings at tech companies, which tools and skills appear in the largest share of postings, and how much do the three roles' tool stacks overlap?**

Tools tracked include SQL, Python, R, Tableau, Power BI, AWS, Azure, GCP, Spark, dbt, Snowflake, PyTorch, and LLM frameworks (LangChain, Hugging Face, OpenAI/Anthropic APIs). The answer is a percentage per tool per role plus an overlap score per role pair, so it can land almost anywhere.

**Who cares.** Students in information science and data programs (me included) choosing which tools to learn before job hunting, and the faculty and advisors who shape those programs. Most advice is "learn Python and SQL," which says nothing about whether analyst and AI tracks need different preparation. If the stacks barely overlap, students should specialize early. If they mostly overlap, the shared core matters more than the title.

**What I expect.** SQL appears in most postings across all three roles. Tableau and Power BI concentrate in analyst postings. Python is near universal for data science and AI but appears in under half of analyst postings. LLM frameworks show up almost only in AI/ML postings. Cloud platforms appear everywhere at similar rates.

**What would surprise me.** (1) LLM tooling showing up in more than 10% of analyst postings, which would mean AI skills are spreading into non-AI roles. (2) Data science and AI/ML stacks overlapping almost completely, which would suggest "AI engineer" is partly a rebrand of data scientist. (3) SQL appearing in fewer than half of AI/ML postings.

## 2. Data source and method

**Source.** Public job board APIs from two applicant tracking systems. No keys, no HTML scraping.

- Greenhouse Job Board API: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` ([docs](https://developers.greenhouse.io/job-board.html))
- Lever Postings API: `GET https://api.lever.co/v0/postings/{company}?mode=json` ([docs](https://github.com/lever/postings-api))

**How I get it.** Python `requests` calls (Ch 1), parsing JSON that differs by source: Greenhouse wraps postings in `{"jobs": [...]}`, Lever returns a bare array (Ch 4). Requests send an identifying User-Agent, pause between calls, and back off on errors (Ch 5). The collector already exists from a side project of mine. New for this class: the research design, a title-based role classifier, a skill keyword dictionary built for these roles, and the weekly snapshot analysis below.

**Scope.**
- Records: every published posting on [N] tech company boards (company list in `config/companies.yml`). All postings are stored; only the three target roles enter the analysis.
- Window and cadence: weekly snapshots every Sunday from Oct 25 through Nov 29, 2026 (6 snapshots).
- Rough count: the Oct 25 pull returned [TOTAL] postings, of which [DATA_AI] fall in the three target roles. With turnover across six weeks I expect roughly [ESTIMATE] unique target-role postings. Postings are deduplicated by job ID, so a posting open all six weeks counts once.

**Analysis.**
1. Classify roles by regex on job title ("data analyst" → analyst, "data scientist" → data science, "machine learning" or "AI engineer" → AI/ML).
2. Match tools with a keyword dictionary using word boundaries, with guarded patterns for ambiguous short names like R, Go, and dbt.
3. **Main table and chart:** share of postings in each role that mention each tool, shown as a heatmap (tools × roles). Share, not raw counts, because the roles have different sample sizes.
4. **Overlap:** Jaccard similarity of each role's top 15 tools for all three role pairs. One number per pair answers "how different are the stacks."

## 3. Ethics and feasibility

**Rules and limits.** Both APIs are documented, public, and require no key for reading posted jobs. Greenhouse documents its Job Board API as a JSON feed of a company's published jobs for building careers pages. Lever's README says its Postings API is designed to help companies create a job site, and the only published rate limit applies to application submissions (2 per second), which I never make. I found no API-specific terms prohibiting read access. For robots.txt, I checked both hosts with Python's `urllib.robotparser` on Oct 25, and it reports my user agent may fetch the API paths I use. My use is noncommercial, low volume, and limited to published data. To stay within limits: one request per second per host, a User-Agent naming the project and my CU email, retry with backoff on 429 or 5xx, a cap of three attempts, and one pull per board per snapshot (about [N] requests per week).

**Personal info.** Postings describe jobs, not people, so there are no usernames or photos. Some descriptions include a recruiter's name or email. I strip email addresses and phone numbers from stored text, never analyze names, and publish only aggregate counts and percentages. Company names stay because they are businesses, not individuals.

**One record, retrieved.**

Request (run Oct 25, 2026, full script in `scripts/sample_record.py`):

```python
UA = "INFO4617-JobMarketResearch/0.1 (CU Boulder student project; YOUR_EMAIL@colorado.edu)"
r = requests.get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true",
                 headers={"User-Agent": UA}, timeout=20)
```

Response (first posting with a data or AI title, trimmed):

```
Status: 200
Total jobs on board: 719
{
  "id": 5416444,
  "title": "Data Analyst",
  "company_name": "Stripe",
  "location": {"name": "Canada"},
  "first_published": "2023-11-01T13:50:50-04:00",
  "updated_at": "2026-10-22T09:15:16-04:00",
  "content_excerpt": "Who we are About Stripe Stripe is a financial infrastructure platform for businesses. Millions of companies—from the world's largest enterprises to the most ambitious startups—use Stripe to accept payments, grow their revenue, and accelerate new business opportunities. Our mission is to increase the..."
}
```

Fields I use: `id` (dedup across snapshots), `title` (role classification), `content` (skill matching, HTML stripped), `company_name`, `location.name`, and `first_published` (posting age; this one has been open since 2023, so long-running postings get flagged). Lever equivalents: `id`, `text`, `descriptionPlain` and `lists`, `categories.location`, `createdAt`.

**Biggest risk and fallback.** The biggest risk is too few analyst postings. Tech companies post far more engineering than analyst roles, and 20 postings make every percentage noisy. Fallback in order: (1) add more Greenhouse boards, which only means adding tokens to a config file; (2) pool all six snapshots into one cross-section instead of comparing weeks; (3) if analyst is still thin, collapse to two groups, analytics versus data science and AI/ML combined. If my scheduled job fails, I run the same script manually each Sunday.
 