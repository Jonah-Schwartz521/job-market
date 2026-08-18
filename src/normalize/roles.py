import re

# Order IS precedence. First match wins.
# Policy: FUNCTION beats DOMAIN for non-engineering roles. A PM working on
# AI is product, not ai-ml, so `product` sits above the domain categories.
# Engineering roles specialize by domain (ML engineer -> ai-ml).
# `software` sits last: it holds the bare-\bengineer\b catch-all.
ROLE_PATTERNS = {
  'product':        r'product manager|product owner|technical program manager|\btpm\b|solutions architect|product designer',
  'ai-ml':          r'\bai engineer|applied ai|applied scientist|machine learning|\bml\b|mlops|\bllm\b|genai|generative ai|prompt engineer|deep learning|computer vision|\bnlp\b|\bai\b.{0,24}(engineer|scientist|research|platform|infrastructure)|(engineer|scientist).{0,24}\bai\b',
  'data-science':   r'data scien(ce|tist)|research scientist|quantitative|statistician|decision scientist',
  'data-analytics': r'data analy(st|tics)|business analyst|analytics engineer|bi (developer|analyst|engineer)|reporting analyst|insights analyst',
  'data-eng':       r'data engineer|data platform|etl|data infrastructure|data architect',
  'it-infra':       r'devops|\bsre\b|site reliability|platform engineer|\binfrastructure\b|systems engineer|cloud engineer|security engineer|it support|help desk|desktop support|network engineer',
  'software':       r'software engineer|backend|frontend|full.?stack|\bswe\b|mobile engineer|android|\bios\b|firmware|embedded|\bengineer\b|engineering manager',
}

def classify_role(title: str) -> str:
    t = (title or "").lower()
    for category, pattern in ROLE_PATTERNS.items():
        if re.search(pattern, t):
            return category
    return 'other'