import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "build"))
import news_post  # noqa: E402


def story(title, summary=""):
    return {"title": title, "summary": summary}


def test_relevant_needs_a_topic_and_germany():
    assert news_post.relevant(story("Germany approves more professional visas amid labor shortage"))
    assert news_post.relevant(story("Mercedes to cut more jobs", "The carmaker plans more cuts in Germany."))
    assert not news_post.relevant(story("Canada hasn't fixed its immigration problem"))   # topic, not Germany
    assert not news_post.relevant(story("Germany's Zverev clinches tennis No. 1 ranking"))  # Germany, no topic
    assert not news_post.relevant(story("Volkswagen logs Q3 loss in Germany"))             # "wage" only inside a word


def test_same_story_from_two_sources_has_one_key():
    assert news_post.key(story("Germany’s October unemployment rises")) == news_post.key(story("Germany's October Unemployment rises"))


def test_dates_from_rss_and_rdf():
    assert news_post._date("Fri, 30 Oct 2026 14:27:30 +0000").isoformat() == "2026-10-30T14:27:30+00:00"
    assert news_post._date("2026-10-30T07:20:00Z").isoformat() == "2026-10-30T07:20:00+00:00"
    assert news_post._date("") is None
