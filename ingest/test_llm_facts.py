import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import llm_facts  # noqa: E402

POSTING = ("8+ years experience in group reporting.\n"
           "Fluent written and verbal English and German.\n"
           "Salary: €70,000 – €85,000 gross per year.\n"
           "We offer visa sponsorship for candidates from outside the EU.")


def test_accepts_answers_backed_by_quotes():
    f = llm_facts.verify({"german": "required", "german_quote": "Fluent written and verbal English and German.",
                          "salary_stated": True, "salary_min_eur_year": 70000, "salary_max_eur_year": 85000,
                          "salary_quote": "Salary: €70,000 – €85,000 gross per year",
                          "visa_sponsorship": True, "visa_quote": "We offer visa sponsorship for candidates"},
                         POSTING, "senior")
    assert f["german"] == "required" and f["salary"] == [70000, 85000] and f["visa"] is True


def test_rejects_invented_quotes_and_implausible_salaries():
    f = llm_facts.verify({"german": "not_required", "german_quote": "No German needed for this role",
                          "salary_stated": True, "salary_min_eur_year": 385000, "salary_quote": "Salary: €70,000",
                          "visa_sponsorship": True, "visa_quote": "We sponsor relocation and visas worldwide"},
                         POSTING, "intern")
    assert "german" not in f      # quote is not in the posting
    assert "salary" not in f      # an intern at €385k is not plausible
    assert "visa" not in f        # "offered" without a real quote


def test_no_salary_means_none_and_not_mentioned_needs_no_german_word():
    f = llm_facts.verify({"salary_stated": False, "german": "not_mentioned"}, POSTING, "mid")
    assert f["salary"] is None and "german" not in f   # the posting does mention German
    g = llm_facts.verify({"german": "not_mentioned"}, "Python developer, Berlin.", "mid")
    assert g["german"] == "not_mentioned"


def test_merge_keeps_both_runs(monkeypatch, tmp_path):
    current, ours = tmp_path / "llm_facts.json", tmp_path / "ours.json"
    current.write_text('{"a": {"h": "1", "german": "required"}, "b": {"h": "2"}}', encoding="utf-8")
    ours.write_text('{"b": {"h": "2", "german": "not_required"}, "c": {"h": "3"}}', encoding="utf-8")
    monkeypatch.setattr(llm_facts, "FACTS_PATH", current)
    assert llm_facts.merge_into_current(str(ours)) == 2
    merged = llm_facts.json.loads(current.read_text(encoding="utf-8"))
    assert set(merged) == {"a", "b", "c"} and merged["b"]["german"] == "not_required"


def test_apply_only_when_posting_unchanged(monkeypatch):
    facts = {"job1": {"h": llm_facts.text_hash(POSTING), "german": "required", "salary": None}}
    monkeypatch.setattr(llm_facts, "_facts", facts)
    row = {"id": "job1", "german_level": "not_mentioned", "salary_min": 400000, "salary_max": 400000}
    assert llm_facts.apply(dict(row), POSTING)["german_level"] == "required"
    assert llm_facts.apply(dict(row), POSTING)["salary_min"] is None
    assert llm_facts.apply(dict(row), POSTING + " edited")["german_level"] == "not_mentioned"
