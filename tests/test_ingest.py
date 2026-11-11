import ingest

DESC = ("<p>We are a remote-first team. You build our APIs in Python with the rest of the engineering team "
        "and talk to customers in English every day.</p>")


def test_jobicy_copy_of_a_direct_job_is_dropped(monkeypatch):
    """The same job from the employer's own board (city Berlin) and from Jobicy (city Remote): keep the board's."""
    board = {"source": "ashby:acme", "url": "https://jobs.ashbyhq.com/acme/1", "title": "Backend Engineer (m/w/d)",
             "company": "Acme", "location": "Berlin", "description_html": DESC}
    jobicy = [{"source": "jobicy", "url": "https://jobicy.com/jobs/1", "title": "Backend Engineer", "company": "ACME",
               "location": "Remote", "is_remote": True, "remote_scope": "eu", "description_html": DESC},
              {"source": "jobicy", "url": "https://jobicy.com/jobs/2", "title": "Data Engineer", "company": "Acme",
               "location": "Remote", "is_remote": True, "remote_scope": "eu", "description_html": DESC}]
    monkeypatch.setattr(ingest.sources, "arbeitnow", lambda max_pages: [])
    monkeypatch.setattr(ingest.discover, "update", lambda *a, **k: 0)
    monkeypatch.setattr(ingest.discover, "boards", lambda: [])
    monkeypatch.setattr(ingest.sources, "company_boards", lambda *a: [board])
    monkeypatch.setattr(ingest.sources, "jobicy", lambda: jobicy)
    monkeypatch.setattr(ingest.sources, "amazon", lambda: [])
    monkeypatch.setattr(ingest.geo, "lookup", lambda *a: None)
    monkeypatch.setattr(ingest.geo, "add_state", lambda *a: None)
    monkeypatch.setattr(ingest.geo, "save", lambda: None)
    rows, _, _ = ingest.collect(max_pages=1)
    assert sorted((r["source"], r["title"]) for r in rows) == [("ashby:acme", "Backend Engineer (m/w/d)"),
                                                               ("jobicy", "Data Engineer")]
