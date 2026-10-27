import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")  # only installed for the insights workflow
sys.path.insert(0, str(Path(__file__).parent))
from insights import make_hints, restore_ai, scam_signals  # noqa: E402

PEERS = {"n": 30, "german_req": 0.6, "no_german": 0.3, "visa": 0.05, "years": 3.0,
         "salary": {"n": 12, "p25": 50000, "p50": 60000, "p75": 70000}}


def job(**kw):
    base = {"title": "Backend Engineer", "seniority": "mid", "salary_min": None, "salary_max": None,
            "years_experience": None, "german_level": "required", "visa_sponsorship": False}
    return {**base, **kw}


def codes(j, peers=PEERS, meta=None, cities=1):
    sal = (j["salary_min"] + (j["salary_max"] or j["salary_min"])) / 2 if j["salary_min"] else np.nan
    return {h["k"] for h in make_hints(j, peers, sal, meta or {}, cities)}


def test_intern_with_400k_is_a_salary_error():
    assert "salary_error" in codes(job(title="Marketing Intern", seniority="intern", salary_min=400000))


def test_salary_against_peers():
    assert "salary_high" in codes(job(salary_min=150000))
    assert "salary_low" in codes(job(salary_min=30000))
    assert "salary_top" in codes(job(salary_min=72000))
    assert not codes(job(salary_min=60000)) & {"salary_high", "salary_low", "salary_top", "salary_error"}


def test_no_salary_comparison_without_enough_peers():
    peers = {k: v for k, v in PEERS.items() if k != "salary"}
    assert not codes(job(salary_min=150000), peers) & {"salary_high", "salary_top"}


def test_experience_and_positive_hints():
    assert "experience_mismatch" in codes(job(seniority="junior", years_experience=6))
    assert "german_rare" in codes(job(german_level="not_required"))
    assert "visa_rare" in codes(job(visa_sponsorship=True))
    assert "many_cities" in codes(job(), cities=7)


def test_scam_signals_need_contact_context():
    assert scam_signals("Send your CV via WhatsApp to +49 170 1234567")
    assert scam_signals("A registration fee of 50 EUR applies")
    assert not scam_signals("We build AI agents for WhatsApp, Telegram and web chat.")
    assert not scam_signals("Our customers pay no fees for transfers.")
    assert not scam_signals("We will never:\nContact you via WhatsApp, Telegram, or similar platforms")
    assert not scam_signals("We do not make job offers via text message, WhatsApp, or instant messaging.")
    assert not scam_signals("Candidates are contacted via WhatsApp or phone, qualified one by one.")


def test_restore_ai_from_database_when_cache_is_lost():
    jobs = [{"id": "a", "db_ai": {"summary": "S", "tasks": ["t"]}, "db_skills": [{"n": "Python", "w": 1.0, "r": 1, "p": 0.4}]},
            {"id": "b", "db_ai": None, "db_skills": [{"n": "SQL", "w": 1.0, "r": 1}]},
            {"id": "c", "db_ai": {"summary": "old"}, "db_skills": None}]
    meta = {"c": {"ai": {"summary": "cached"}}}
    assert restore_ai(jobs, meta) == 1
    assert meta["a"]["ai"] == {"summary": "S", "tasks": ["t"], "skills": [{"n": "Python", "w": 1.0, "r": 1}]}
    assert "ai" not in meta["b"]                    # no analysis saved: the LLM still has to read it
    assert meta["c"]["ai"]["summary"] == "cached"   # the cache wins when it has one
    assert all("db_ai" not in j and "db_skills" not in j for j in jobs)
