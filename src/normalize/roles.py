import re

# Dict order IS the precedence policy. First match wins, most specific first.
# "Software Engineer, Machine Learning" -> ai-ml, not software.
ROLE_PATTERNS = {
  'ai-ml':          r'\bai engineer|applied ai|applied scientist|machine learning|ml engineer|mlops|\bllm\b|genai|generative ai|prompt engineer|deep learning|computer vision|\bnlp\b',
  'data-science':   r'data scien(ce|tist)|research scientist|quantitative|statistician|decision scientist',
  'data-analytics': r'data analy(st|tics)|business analyst|analytics engineer|bi (developer|analyst|engineer)|reporting analyst|insights analyst',
  'data-eng':       r'data engineer|data platform|etl|data infrastructure|data architect',
  'software':       r'software engineer|backend|frontend|full.?stack|\bswe\b|mobile engineer',
  'it-infra':       r'devops|\bsre\b|site reliability|platform engineer|infrastructure engineer|systems engineer|cloud engineer|security engineer',
  'product':        r'product manager|technical program manager|\btpm\b|solutions architect',
}

def classify_role(title: str) -> str:
    t = (title or "").lower()
    for category, pattern in ROLE_PATTERNS.items():
        if re.search(pattern, t):
            return category
    return 'other'