import requests, json, re, html
from urllib.robotparser import RobotFileParser

UA = "INFO4617-JobMarketResearch/0.1 (CU Boulder student project; josc6888@colorado.edu)"
url = "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"

r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
print("GET", url)
print("Status:", r.status_code)
jobs = r.json()["jobs"]
print("Total jobs on board:", len(jobs))

pat = re.compile(r"data (analyst|scientist|engineer)|analytics|machine learning|ml engineer|ai engineer", re.I)
job = next((j for j in jobs if pat.search(j["title"])), jobs[0])

text = re.sub(r"<[^>]+>", " ", html.unescape(job["content"]))
text = re.sub(r"\s+", " ", html.unescape(text)).strip()

record = {k: job.get(k) for k in ["id", "title", "company_name", "location", "first_published", "updated_at"]}
record["content_excerpt"] = text[:300] + "..."
print(json.dumps(record, indent=2, ensure_ascii=False))

for host, path in [("https://boards-api.greenhouse.io", "/v1/boards/stripe/jobs"),
                   ("https://api.lever.co", "/v0/postings/spotify")]:
    rp = RobotFileParser(host + "/robots.txt"); rp.read()
    print(host, "| can_fetch:", rp.can_fetch("INFO4617-JobMarketResearch", host + path))
