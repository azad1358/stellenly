"""Rule-based skill extraction, ranked by importance.

Importance comes from *where* a skill is mentioned: in the title, under
"Requirements / Your profile", under "What you'll do", under "Nice to have",
or only in company boilerplate. Used when no LLM is configured, and as a
fallback when the LLM is unavailable.
"""
from __future__ import annotations

import re

# Display name -> pattern (matched case-insensitively on word boundaries unless the pattern says otherwise).
SKILLS: dict[str, str] = {
    # Programming languages
    "Python": r"python", "Java": r"java(?!\s?script)", "JavaScript": r"javascript|\bjs\b", "TypeScript": r"typescript",
    "Go": r"golang|\bgo\b(?=[\s,/)]+(?:developer|engineer|services|backend|microservices|and|or|,))",
    "Rust": r"rust\b(?!ic)", "C++": r"c\+\+", "C#": r"c#|\.net\b|dotnet", "C": r"\bc\b(?=\s*(?:/|,|and|or)\s*c\+\+)",
    "Kotlin": r"kotlin", "Swift": r"swift\b(?!\s?code)", "Scala": r"scala\b", "Ruby": r"ruby", "PHP": r"php",
    "R": r"\br\b(?=\s*(?:,|/|and|or)\s*(?:python|sql|stata|matlab))|(?<=python, )r\b|\br programming",
    "SQL": r"sql\b|t-sql|pl/sql", "Bash": r"bash|shell scripting", "MATLAB": r"matlab", "Elixir": r"elixir",
    "Dart": r"\bdart\b", "Solidity": r"solidity", "VHDL/Verilog": r"vhdl|verilog|systemverilog",
    # Web / mobile
    "React": r"react(?:\.js|js)?\b(?!ive)", "React Native": r"react native", "Next.js": r"next\.?js",
    "Vue": r"vue(?:\.js)?", "Angular": r"angular", "Node.js": r"node(?:\.js|js)\b", "HTML/CSS": r"html|css\b",
    "GraphQL": r"graphql", "REST APIs": r"rest(?:ful)?\s?apis?|rest services", "Django": r"django", "FastAPI": r"fastapi",
    "Flask": r"flask", "Spring": r"spring(?:\s?boot)?\b", "Rails": r"ruby on rails|rails (?:developer|engineer|framework|apps?)", "Laravel": r"laravel",
    "Flutter": r"flutter", "iOS": r"\bios\b", "Android": r"android",
    # Data & ML
    "Machine learning": r"machine learning|\bml\b(?!\s?ops)", "Deep learning": r"deep learning|neural networks?",
    "LLMs": r"\bllms?\b|large language models?|generative ai|genai|gpt-?\d?", "NLP": r"\bnlp\b|natural language processing",
    "Computer vision": r"computer vision", "PyTorch": r"pytorch", "TensorFlow": r"tensorflow|keras",
    "scikit-learn": r"scikit-?learn|sklearn", "Pandas": r"pandas", "Spark": r"spark\b|pyspark", "Kafka": r"kafka",
    "Airflow": r"airflow", "dbt": r"\bdbt\b", "Snowflake": r"snowflake", "BigQuery": r"bigquery", "Databricks": r"databricks",
    "Statistics": r"statistics|statistical (?:analysis|modell?ing|methods)", "A/B testing": r"a/b test\w*", "MLOps": r"mlops",
    "RAG": r"\brag\b|retrieval[- ]augmented", "Data modelling": r"data model(?:l)?ing",
    # Analytics / BI
    "Excel": r"\bexcel\b|spreadsheets?", "Tableau": r"tableau", "Power BI": r"power ?bi", "Looker": r"looker",
    "Google Analytics": r"google analytics|\bga4\b", "Data analysis": r"data analy(?:sis|tics)",
    # Cloud & infrastructure
    "AWS": r"\baws\b|amazon web services", "Azure": r"\bazure\b", "GCP": r"\bgcp\b|google cloud",
    "Kubernetes": r"kubernetes|\bk8s\b", "Docker": r"docker|containeri[sz]ation", "Terraform": r"terraform",
    "CI/CD": r"ci/cd|continuous (?:integration|delivery|deployment)|github actions|gitlab ci|jenkins",
    "Linux": r"linux|unix", "Microservices": r"microservices?", "PostgreSQL": r"postgres(?:ql)?",
    "MySQL": r"mysql", "MongoDB": r"mongo(?:db)?", "Redis": r"redis", "Elasticsearch": r"elastic ?search",
    "Distributed systems": r"distributed systems", "Observability": r"observability|prometheus|opentelemetry",
    "Security": r"cyber ?security|information security|appsec|penetration test|\bsiem\b|iso 27001",
    "Networking": r"tcp/ip|network (?:engineering|protocols|security|infrastructure)|\bvpn\b",
    # Embedded / hardware / engineering
    "Embedded": r"embedded", "RTOS": r"\brtos\b|freertos", "PCB design": r"pcb|altium", "FPGA": r"fpga",
    "CAD": r"\bcad\b|solidworks|catia|siemens nx|creo", "FEM/Simulation": r"\bfem\b|\bfea\b|ansys|abaqus|simulation",
    "Robotics": r"robotics|\bros2?\b", "Systems engineering": r"systems engineering|requirements engineering",
    "Automotive": r"automotive|autosar|iso 26262", "Aerospace": r"aerospace|avionics|do-178",
    # Product, design, delivery
    "Product management": r"product management|product discovery|product roadmaps?", "Agile/Scrum": r"agile|scrum|kanban",
    "Jira": r"\bjira\b", "Figma": r"figma", "UX research": r"ux research|user research|usability",
    "UI design": r"ui design|interaction design|visual design", "Design systems": r"design systems?",
    "Project management": r"project management|\bpmp\b|prince2", "Stakeholder management": r"stakeholder management|managing stakeholders|stakeholder (?:communication|engagement|alignment)",
    # Business, sales, marketing, finance
    "Salesforce": r"salesforce", "HubSpot": r"hubspot", "CRM": r"\bcrm\b", "B2B sales": r"b2b sales|saas sales|new business",
    "Account management": r"account management", "Negotiation": r"negotiation skills|contract negotiation|negotiat(?:e|ing) (?:contracts|deals|terms|prices)", "Lead generation": r"lead generation|prospecting",
    "SEO": r"\bseo\b", "SEM/Paid ads": r"\bsem\b|google ads|paid (?:social|media|search)|performance marketing",
    "Content marketing": r"content marketing|copywriting", "Social media": r"social media",
    "Marketing automation": r"marketing automation|marketo|braze|customer\.io",
    "Financial modelling": r"financial model(?:l)?ing|valuation", "Accounting": r"accounting|bookkeeping|ifrs|hgb|gaap",
    "Controlling": r"controlling|fp&a|budgeting|forecasting", "SAP": r"\bsap\b", "Tax": r"\btax\b|vat",
    "Compliance": r"compliance (?:management|monitoring|officer|framework|experience)|\baml\b|\bkyc\b|"
                  r"regulatory (?:reporting|compliance|affairs|requirements)", "Risk management": r"risk management",
    "Legal": r"legal (?:counsel|advice|research|drafting|background|degree)|contract (?:law|drafting|negotiation)|litigation",
    # People & support
    "Recruiting": r"full[- ]cycle recruit\w*|talent acquisition|candidate sourcing|(?:experience in|background in) recruit\w*", "HR": r"\bhr\b|human resources|people operations",
    "Customer support": r"customer support|customer service|helpdesk|zendesk",
    "Customer success": r"customer success", "Operations": r"operations management|process optimi[sz]ation",
    "Supply chain": r"supply chain|procurement|logistics (?:management|operations|experience)",
    # Languages (spoken)
    "English": r"english", "German": r"german\b(?!y)", "French": r"french", "Spanish": r"spanish", "Italian": r"italian",
    "Dutch": r"dutch", "Polish": r"polish\b",
    # Soft skills that postings stress
    "Communication": r"communication skills|communicat(?:e|ion) (?:clearly|effectively)",
    "Leadership": r"leadership (?:experience|skills)|people management|(?:managing|leading) (?:a )?teams?|team leadership",
    "Mentoring": r"mentor(?:ing)? (?:junior|engineers|others|team)|coach(?:ing)? (?:junior|engineers|others)",
}
_COMPILED = {name: re.compile(rf"(?<![\w+#.])(?:{pat})(?!\w)", re.I) for name, pat in SKILLS.items()}

_REQ = re.compile(r"requirement|qualification|what you (?:bring|need|have)|you(?:'ll)? (?:bring|have)|your profile|"
                  r"who you are|about you|must[- ]have|we(?:'re| are)? look(?:ing)? for|what we expect|skills|"
                  r"your (?:background|experience)|ihr profil|dein profil|you should have", re.I)
_NICE = re.compile(r"nice[- ]to[- ]have|bonus|a plus|is a plus|preferred|advantage|desirable|good to have|"
                   r"extra points|wünschenswert|ideally", re.I)
_RESP = re.compile(r"responsibilit|what you(?:'ll| will) do|your (?:tasks|role|mission|impact)|the role|"
                   r"day[- ]to[- ]day|you will|ihre aufgaben|deine aufgaben|in this role", re.I)
_OTHER = re.compile(r"about us|who we are|benefits|what we offer|perks|why join|our (?:offer|company|mission)|"
                    r"wir bieten|about the company|equal opportunit|diversity", re.I)
WEIGHT = {"req": 1.0, "resp": 0.7, "nice": 0.45, "other": 0.25, None: 0.6}


def _section(line: str, current):
    """A short line that names a section ("Your profile:", "Nice to have") switches the section."""
    if len(line) > 70:
        return current
    for name, pat in (("nice", _NICE), ("req", _REQ), ("resp", _RESP), ("other", _OTHER)):
        if pat.search(line):
            return name
    return current


_BY_LOWER = {n.lower(): n for n in SKILLS}


def canonical_skill(name: str) -> str:
    """Map an LLM's spelling ("python", "Postgres") to our display name when we know the skill."""
    for n, rx in _COMPILED.items():
        if name.lower() == n.lower() or rx.fullmatch(name.strip()):
            return n
    return _BY_LOWER.get(name.lower(), name[:1].upper() + name[1:])


def extract_skills(title: str, text: str, limit: int = 10, company: str = "") -> list[dict]:
    """[{"n": "Python", "w": 1.0, "r": 1}, ...] sorted by importance; w is relative (top skill = 1),
    r = 1 if it reads as required, 0 if only "nice to have"."""
    hits: dict[str, list[float]] = {}
    sections: dict[str, set] = {}
    section = None
    for raw in (text or "").splitlines():
        line = raw.strip(" \t•*-–·")
        if not line:
            continue
        section = _section(line, section)
        line_section = "nice" if _NICE.search(line) and section != "other" else section
        for name, rx in _COMPILED.items():
            if rx.search(line):
                hits.setdefault(name, []).append(WEIGHT[line_section])
                sections.setdefault(name, set()).add(line_section)
    for name, rx in _COMPILED.items():
        if rx.search(title or ""):
            hits.setdefault(name, []).append(1.6)
            sections.setdefault(name, set()).add("title")

    # English is implied on this site; the employer's own name ("Databricks" at Databricks) is not a skill.
    hits.pop("English", None)
    own = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    for name in [n for n in hits if own and re.sub(r"[^a-z0-9]", "", n.lower()) in own]:
        hits.pop(name)
    scored = []
    for name, ws in hits.items():
        ws = sorted(ws, reverse=True)
        score = sum(w * (0.5 ** k) for k, w in enumerate(ws))  # repeated mentions count, with diminishing returns
        required = bool(sections[name] & {"req", "title", "resp", None}) or not sections[name] <= {"nice", "other"}
        if sections[name] <= {"other"}:
            score *= 0.5  # only in company boilerplate / benefits
        scored.append((name, score, required))
    if not scored:
        return []
    top = max(s for _, s, _ in scored)
    scored = [(n, s / top, r) for n, s, r in scored if s / top >= 0.15]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [{"n": n, "w": round(w, 2), "r": int(r)} for n, w, r in scored[:limit]]
