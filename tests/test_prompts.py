import re

import prompts

# Every prompt the code asks for, with the placeholders the code fills in.
USED = {
    "job_analysis": {"title", "company", "text"},
    "salary_check": {"title", "company", "salary_min", "salary_max", "snippets"},
    "skill_report": {"role", "n_jobs", "rows", "peers"},
    "skill_report_peers": {"n"},
    "skill_report_no_peers": set(),
}


def test_every_prompt_is_in_prompts_md_with_its_placeholders():
    found = prompts._sections()
    for name, keys in USED.items():
        assert name in found, f"## {name} missing in prompts.md"
        placeholders = set(re.findall(r"\{(\w+)\}", found[name]))
        assert placeholders == keys, f"{name}: prompts.md has {placeholders}, the code fills {keys}"


def test_get_fills_placeholders_once_and_keeps_json_braces():
    out = prompts.get("job_analysis", title="Data {company} Engineer", company="ACME", text="Python")
    assert "Title: Data {company} Engineer\nCompany: ACME" in out  # a value is not filled in again
    assert out.startswith("You help") and '{"summary":' in out
