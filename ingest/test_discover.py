import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import discover  # noqa: E402
import sources  # noqa: E402


def test_parse_board_recognises_the_common_systems():
    cases = {
        "https://jobs.ashbyhq.com/n8n/01d9f6ac/application?utm_source=arbeitnow": {"ats": "ashby", "board": "n8n"},
        "https://job-boards.eu.greenhouse.io/raisin/jobs/4919850101": {"ats": "greenhouse", "board": "raisin", "region": "eu"},
        "https://boards.greenhouse.io/acme/jobs/1": {"ats": "greenhouse", "board": "acme"},
        "https://jobs.lever.co/acme/abc": {"ats": "lever", "board": "acme"},
        "https://jobs.eu.lever.co/unzer/abc": {"ats": "lever", "board": "unzer", "region": "eu"},
        "https://tado.jobs.personio.de/job/2502124?language=en": {"ats": "personio", "board": "tado"},
        "https://acme.jobs.personio.com/job/1": {"ats": "personio", "board": "acme", "region": "com"},
        "https://instagrid.recruitee.com/o/test-engineer": {"ats": "recruitee", "board": "instagrid"},
        "https://careers.instagrid.co/o/test-engineer?utm_source=x":
            {"ats": "recruitee", "board": "instagrid", "region": "https://careers.instagrid.co"},
        "https://apply.workable.com/acme/j/ABC123/": {"ats": "workable", "board": "acme"},
        "https://jobs.smartrecruiters.com/Auto1/744000157760969-people": {"ats": "smartrecruiters", "board": "Auto1"},
    }
    for url, want in cases.items():
        assert discover.parse_board(url) == want, url


def test_parse_board_ignores_unknown_or_unnamed():
    assert discover.parse_board("https://apply.workable.com/j/DC4B9774F4") is None
    assert discover.parse_board("https://careers.hellofresh.com/global/en/job/8167337?gh_jid=8167337") is None
    assert discover.parse_board("") is None


class Resp:
    def __init__(self, content=b"", payload=None):
        self.content, self._payload, self.status_code, self.headers = content, payload, 200, {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


PERSONIO_XML = """<?xml version="1.0" encoding="UTF-8"?><workzag-jobs>
<position><id>1</id><office>Germany - Munich</office><department>Finance</department><name>Team Lead Accounting</name>
<jobDescriptions><jobDescription><name>Your tasks</name><value><![CDATA[<p>Close the books.</p>]]></value></jobDescription></jobDescriptions>
<employmentType>permanent</employmentType><createdAt>2026-01-22T09:48:25+00:00</createdAt></position>
<position><id>2</id><office>London</office><name>UK role</name><jobDescriptions/></position>
</workzag-jobs>""".encode()


def test_personio_reads_german_positions(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url, **kw: Resp(content=PERSONIO_XML))
    jobs = list(sources.personio("tado", "tado"))
    assert [j["title"] for j in jobs] == ["Team Lead Accounting"]
    assert jobs[0]["url"] == "https://tado.jobs.personio.de/job/1?language=en"
    assert "Close the books" in jobs[0]["description_html"] and jobs[0]["posted_at"].startswith("2026-01-22")


def test_recruitee_keeps_germany_only(monkeypatch):
    offers = {"offers": [
        {"id": 1, "title": "Engineer", "city": "Berlin", "country": "Germany", "country_code": "DE",
         "careers_url": "https://x.recruitee.com/o/engineer", "description": "<p>Build</p>", "published_at": "2026-10-26 16:28:15 UTC"},
        {"id": 2, "title": "UK Sales", "city": "Liverpool", "country": "United Kingdom", "country_code": "GB"}]}
    monkeypatch.setattr(sources, "_get", lambda url, **kw: Resp(payload=offers))
    jobs = list(sources.recruitee("x", "X GmbH"))
    assert [j["title"] for j in jobs] == ["Engineer"] and jobs[0]["posted_at"] == "2026-10-26T16:28:15+00:00"


def test_smartrecruiters_fetches_english_postings_only(monkeypatch):
    listing = {"totalFound": 2, "content": [
        {"ref": "https://api/p/1", "language": {"code": "en"}},
        {"ref": "https://api/p/2", "language": {"code": "de"}}]}
    detail = {"id": 1, "name": "Data Engineer", "postingUrl": "https://jobs.smartrecruiters.com/Auto1/1",
              "location": {"fullLocation": "Berlin, Germany", "remote": False}, "releasedDate": "2026-10-26T09:46:02Z",
              "jobAd": {"sections": {"jobDescription": {"title": "The role", "text": "<p>Pipelines</p>"}}}}
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return Resp(payload=listing if "postings" in url and "/p/" not in url else detail)
    monkeypatch.setattr(sources, "_get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    jobs = list(sources.smartrecruiters("Auto1", "AUTO1"))
    assert [j["title"] for j in jobs] == ["Data Engineer"] and "https://api/p/2" not in calls
