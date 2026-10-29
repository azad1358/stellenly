"""LLM prompts, loaded from prompts.md at the repo root (one "## name" section per prompt, text in a ``` block).

    get("job_analysis", title=..., company=..., text=...) -> str
"""
import functools
import re
from pathlib import Path

FILE = Path(__file__).parent.parent / "prompts.md"


@functools.cache
def _sections() -> dict[str, str]:
    md = FILE.read_text(encoding="utf-8")
    return {m[1]: m[2] for m in re.finditer(r"^## (\w+)\n.*?^```\n(.*?)\n```$", md, re.M | re.S)}


def get(name: str, **values) -> str:
    """The prompt `name` with each {key} replaced by values[key]; other braces (JSON examples) stay as they are.
    One pass, so a value that contains "{title}" (e.g. a posting) is never filled in again."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m[1]]) if m[1] in values else m[0], _sections()[name])


if __name__ == "__main__":
    # The Skill check function can't read prompts.md on Supabase's servers, so the deploy turns it into JSON
    # next to the function, which it imports:  python ingest/prompts.py supabase/functions/skill-report/prompts.json
    import json
    import sys
    Path(sys.argv[1]).write_text(json.dumps(_sections(), ensure_ascii=False, indent=1), encoding="utf-8")
