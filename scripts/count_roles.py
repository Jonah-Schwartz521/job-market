import time, yaml, requests
from collections import Counter
from src.normalize.roles import classify_role

UA = "INFO4617-JobMarketResearch/0.1 (CU Boulder student project; josc6888@colorado.edu)"
cos = [c for c in yaml.safe_load(open("config/companies.yml"))["companies"] if c.get("active")]

total, roles, per_co, failed = 0, Counter(), {}, []
for c in cos:
    if c["ats"] == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{c['board_token']}/jobs"
    else:
        url = f"https://api.lever.co/v0/postings/{c['board_token']}?mode=json"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        data = r.json()
        items = data["jobs"] if c["ats"] == "greenhouse" else data
        if r.status_code != 200 or not isinstance(items, list):
            raise ValueError(f"status {r.status_code}: {str(data)[:80]}")
        titles = [j["title"] if c["ats"] == "greenhouse" else j["text"] for j in items]
    except Exception as e:
        failed.append(c["name"]); print("FAILED:", c["name"], e); time.sleep(1); continue
    cats = Counter(classify_role(t) for t in titles)
    total += len(titles); roles += cats
    per_co[c["name"]] = sum(cats[k] for k in ("data-analytics", "data-science", "ai-ml"))
    print("done:", c["name"], len(titles))
    time.sleep(1)

print("Boards ok:", len(cos) - len(failed), "| failed:", failed)
print("Total postings:", total)
for k in ("data-analytics", "data-science", "ai-ml"):
    print(f"{k}: {roles[k]}")
print("Target roles per company:", per_co)
