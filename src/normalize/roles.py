import re

# Order IS precedence. First match wins.
#
# Layer 1: technical specializations (most specific)
# Layer 2: business functions
# Layer 3: software, which holds the bare-\bengineer\b catch-all and must
#          stay last so "Sales Engineer" lands in sales, not software.
#
# Policy: FUNCTION beats DOMAIN for non-engineering roles. A PM working on
# AI is product; an engineer working on ML is ai-ml.
ROLE_PATTERNS = {
  'product':        r'product manager|product owner|technical program manager|\btpm\b|solutions architect|product designer',
  'ai-ml':          r'\bai engineer|applied ai|applied scientist|machine learning|\bml\b|mlops|\bllm\b|genai|generative ai|prompt engineer|deep learning|computer vision|\bnlp\b|\bai\b.{0,24}(engineer|scientist|research|platform|infrastructure)|(engineer|scientist).{0,24}\bai\b',
  'data-science':   r'data scien(ce|tist)|research scientist|quantitative|statistician|decision scientist|biostatistic|econometric',
  'data-analytics': r'data analy(st|tics)|business analyst|analytics engineer|bi (developer|analyst|engineer)|reporting analyst|insights analyst|analytics (services|consulting)|consultant,? analytics',
  'data-eng':       r'data engineer|data platform|\betl\b|data infrastructure|data architect',
  'it-infra':       r'devops|\bsre\b|site reliability|platform engineer|\binfrastructure\b|systems engineer|cloud engineer|security engineer|it support|help desk|desktop support|network engineer|\bit (analyst|manager|director|administrator|specialist|operations)\b|\bciso\b|chief information security|\binformation security\b|\binformation technology\b',

  'clinical':       r'\bnurse\b|\brn\b|clinician|physician|\bmd\b|pharmacis|therapis|counselor|psychiatr|psycholog|medical director|clinical (lead|manager|specialist|operations|program)|care (coordinator|manager|navigator)|patient care',
  'sales':          r'account executive|\bsales\b|business development|\bbdr\b|\bsdr\b|partnerships|partner development|channel manager|revenue (lead|manager)|go.to.market|\bgtm\b|solutions (consultant|engineer)|sales engineer',
  'legal':          r'counsel\b|\blegal\b|paralegal|attorney|litigation|\bprivacy\b|regulatory affairs|contracts manager|intellectual property',
  'finance':        r'\bfinanc(e|ial)\b|\baccount(ing|ant)\b|controller|treasury|\bfp&a\b|\baudit|bookkeep|payroll|tax\b|revenue operations|billing (analyst|manager|specialist)',
  'risk-compliance': r'\brisk\b|complian|\bfraud\b|\baml\b|anti.money|underwrit|\bkyc\b|financial crime|sanctions|\bcredit\b(?!.{0,12}card design)|internal control',
  'people':         r'recruit|talent acquisition|\bhr\b|human resources|people (ops|operations|partner|business partner)|compensation|benefits (manager|analyst)|learning and development|employee experience',
  'marketing':      r'\bmarketing\b|\bbrand\b|demand generation|content (strategist|manager|marketer|writer)|communications|public relations|social media|seo\b|copywriter|events manager',
  'support':        r'customer (success|support|experience|care)|technical support|account manager|client (services|partner|success)|implementation (manager|specialist|consultant)|onboarding specialist|support specialist|escalation|outcomes? architect|knowledge architect',
  'design':         r'\bdesigner\b|\bux\b|\bui\b|user (research|experience)|visual design|brand design|design (lead|manager|director)|creative director',
  'operations':     r'\boperations\b|\bops\b|supply chain|logistics|procurement|vendor (lead|manager)|facilities|workforce management|business operations|program manager',

  'software':       r'software engineer|backend|frontend|full.?stack|\bswe\b|mobile engineer|android|\bios\b|firmware|embedded|\bengineer\b|engineering manager|developer\b|architect\b',
}


# Business-function categories describe what a person DOES. An engineer
# building risk systems is software, not risk-compliance, and "Sales
# (Financial Services)" is sales in a finance vertical, not finance.
# Engineering titles therefore skip the business layer entirely.
BUSINESS = frozenset({
    'clinical', 'legal', 'finance', 'risk-compliance', 'people',
    'marketing', 'sales', 'support', 'design', 'operations',
})

ENGINEERING_TITLE = re.compile(
    r'\bengineer\b|\bengineering\b|\bdeveloper\b|\bswe\b|\barchitect\b|\bprogrammer\b'
)

# A business qualifier IMMEDIATELY before an engineering noun means the person
# is not an engineer: "Legal Engineer" is a practising lawyer, "Outcomes
# Architect" is customer success. These titles keep the business layer.
#
# Adjacency is the whole rule. Matching the qualifier anywhere in the title
# wrongly catches "Senior Software Engineer - Cloud Partner Integrations".
#
# Note this is what actually makes the docstring above true. Without it the
# blanket skip below defeated the ordering and "Sales Engineer" became
# software, not sales.
PSEUDO_ENGINEERING = re.compile(
    r'\b(legal|sales|solution|solutions|outcome|outcomes|account|customer|'
    r'client|support|success|partner|revenue|commercial|marketing|people|'
    r'talent|implementation|value|presales|pre-sales)[\s,/-]+'
    r'(engineer|engineers|engineering|architect|architects)\b'
)


def classify_role(title: str) -> str:
    t = (title or "").lower()
    is_eng = bool(ENGINEERING_TITLE.search(t)) and not PSEUDO_ENGINEERING.search(t)
    for category, pattern in ROLE_PATTERNS.items():
        if is_eng and category in BUSINESS:
            continue
        if re.search(pattern, t):
            return category
    return 'other'