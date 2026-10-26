import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from skills import canonical_skill, extract_skills  # noqa: E402

POSTING = """About the role
You will build data pipelines in Python and SQL.
Your profile
- 3+ years with Python, SQL and Airflow
- Experience with AWS and Docker
Nice to have
- Kubernetes
About us
We use React internally and offer great benefits."""


def test_ranks_title_and_requirements_first():
    names = [s["n"] for s in extract_skills("Senior Data Engineer (Python)", POSTING)]
    assert names[0] == "Python"
    assert names.index("SQL") < names.index("Kubernetes")


def test_nice_to_have_is_not_required():
    by = {s["n"]: s for s in extract_skills("Data Engineer", POSTING)}
    assert by["Kubernetes"]["r"] == 0 and by["Airflow"]["r"] == 1


def test_boilerplate_and_word_boundaries():
    names = {s["n"] for s in extract_skills("Developer", "Pythonic code. Our recruiting team will contact you. "
                                                         "We work on guardrails and JavaScript.")}
    assert "Python" not in names and "Recruiting" not in names and "Rails" not in names
    assert "JavaScript" in names and "Java" not in names


def test_employer_name_is_not_a_skill():
    names = {s["n"] for s in extract_skills("Solutions Architect", "Requirements: Databricks, Spark, SQL",
                                            company="Databricks")}
    assert "Databricks" not in names and "Spark" in names


def test_canonical_names_for_llm_output():
    assert canonical_skill("python") == "Python"
    assert canonical_skill("postgres") == "PostgreSQL"
    assert canonical_skill("prompt engineering") == "Prompt engineering"
