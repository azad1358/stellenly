import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from enrich import (  # noqa: E402
    abroad, enrich, generic_location, german_level, html_to_text, strip_boilerplate, in_germany, is_agency, job_id, normalize_city, parse_salary,
    relocation, remote_type, seniority, visa_sponsorship, years_experience,
)


# --- German level -----------------------------------------------------------
def test_german_required():
    assert german_level("You speak fluent German and English.") == "required"
    assert german_level("Requirements: German C1 level.") == "required"
    assert german_level("German language skills are mandatory.") == "required"
    assert german_level("Both English and German written and spoken.") == "required"


def test_german_nice_to_have():
    assert german_level("Fluent English required. German is a plus.") == "nice_to_have"
    assert german_level("Good command of German would be a big advantage.") == "nice_to_have"
    assert german_level("Basic German is appreciated.") == "nice_to_have"


def test_german_not_required():
    assert german_level("No German required - our team speaks English.") == "not_required"
    assert german_level("German is not required for this role.") == "not_required"


def test_german_not_mentioned():
    assert german_level("We build great software in Berlin with Python.") == "not_mentioned"


def test_required_wins_over_nice():
    txt = "German is a plus for the team. You must speak German with clients."
    assert german_level(txt) == "required"


# --- Salary ---------------------------------------------------------------
def test_salary_ranges():
    assert parse_salary("Salary: 65.000 - 75.000 € per year") == (65000, 75000)
    assert parse_salary("We pay €60k–€80k plus equity") == (60000, 80000)
    assert parse_salary("Gehalt 50,000 to 70,000 EUR") == (50000, 70000)


def test_salary_monthly_and_hourly():
    assert parse_salary("4.500 - 5.000 € per month") == (54000, 60000)
    assert parse_salary("15 - 17 € per hour") == (None, None)


def test_salary_none():
    assert parse_salary("Competitive salary and 30 days of vacation") == (None, None)
    assert parse_salary("We have 50 - 60 people in 3 offices") == (None, None)


# --- Others ---------------------------------------------------------------
def test_years_and_seniority():
    assert years_experience("You have 3+ years of professional experience in Python") == 3
    assert years_experience("At least 5 years experience") == 5
    assert seniority("Senior Backend Engineer", None) == "senior"
    assert seniority("Werkstudent Marketing", None) == "intern"
    assert seniority("Backend Engineer", 1) == "junior"
    assert seniority("Head of Growth", None) == "lead"


def test_remote_type():
    assert remote_type(True, "Engineer", "We are remote-first.") == "remote_de"
    assert remote_type(False, "Engineer", "Hybrid: 2 days per week in the office") == "hybrid"
    assert remote_type(True, "Engineer", "Work remote (EU) from anywhere in Europe") == "remote_eu"
    assert remote_type(False, "Engineer", "Office in Munich") == "onsite"


def test_visa_and_relocation():
    assert visa_sponsorship("We offer visa sponsorship and relocation support.")
    assert not visa_sponsorship("Unfortunately we cannot sponsor visas.")
    assert relocation("Relocation package included")
    assert not relocation("Free coffee")


def test_agency():
    assert is_agency("Hays AG", "")
    assert is_agency("Acme", "On behalf of our client, a fintech in Berlin...")
    assert not is_agency("Zalando SE", "Join our team")


def test_city_and_dedupe():
    assert normalize_city("München, Bayern") == "Munich"
    assert normalize_city("Frankfurt am Main") == "Frankfurt"
    assert normalize_city("Germany") is None
    assert job_id("Backend Engineer (m/w/d)", "Acme GmbH", "Berlin") == \
        job_id("backend engineer", "ACME GmbH", "berlin")


def test_html_to_text():
    assert html_to_text("<p>Hello&nbsp;<b>world</b></p><ul><li>A</li></ul>") == "Hello world\n• A"


def test_enrich_end_to_end():
    raw = {
        "source": "arbeitnow", "source_id": "x1", "url": "https://example.com/job/1",
        "title": "Senior Python Engineer (m/w/d)", "company": "Acme GmbH",
        "location": "Berlin, Germany", "is_remote": False, "tags": ["Software Development"],
        "job_types": ["full time"], "posted_at": "2026-10-20T10:00:00+00:00",
        "description_html": (
            "<p>We are an English-speaking team building data products with our customers.</p>"
            "<p>You have 5+ years of experience with Python and AWS. German is a plus.</p>"
            "<p>Salary: 70.000 - 85.000 EUR per year. We offer visa sponsorship and a relocation package.</p>"
            "<p>Hybrid: 2 days per week in the office.</p>"
        ),
    }
    row = enrich(raw)
    assert row is not None
    assert row["german_level"] == "nice_to_have"
    assert (row["salary_min"], row["salary_max"]) == (70000, 85000)
    assert row["visa_sponsorship"] and row["relocation"]
    assert row["remote_type"] == "hybrid"
    assert row["seniority"] == "senior"
    assert row["city"] == "Berlin"
    assert {"python", "cloud", "visa-sponsorship", "senior", "software-development"} <= set(row["tags"])


def test_enrich_skips_german_posting():
    raw = {
        "source": "arbeitnow", "url": "https://example.com/2", "title": "Sachbearbeiter (m/w/d)",
        "company": "Muster GmbH", "location": "Köln",
        "description_html": "<p>Wir suchen eine engagierte Person für unser Team. Sie haben "
                            "eine abgeschlossene Ausbildung und arbeiten gerne mit Kunden.</p>",
    }
    assert enrich(raw) is None


# --- Location ---------------------------------------------------------------
def test_in_germany():
    for loc in ["Berlin", "München, Bayern", "Muenchen", "Walldorf, Baden-Württemberg",
                "Remote (Germany)", "Hamburg, DE", "London or Berlin", "Frankfurt am Main",
                "Herzogenaurach", "Düsseldorf; Paris", "Nordrhein-Westfalen"]:
        assert in_germany(loc), loc
    for loc in ["London", "Hanover, NH", "Berlin, CT, USA", "Remote", "Paris, France",
                "San Francisco, CA", "Essential Services", None, ""]:
        assert not in_germany(loc), loc


def test_normalize_city_variants():
    assert normalize_city("Köln") == "Cologne"
    assert normalize_city("Nuernberg, Germany") == "Nuremberg"
    assert normalize_city("Halle (Saale)") == "Halle"
    assert normalize_city("Bavaria, Germany") is None
    assert normalize_city("Garching bei München") == "Garching"


def test_normalize_city_picks_german_part():
    assert normalize_city("Munich - London") == "Munich"
    assert normalize_city("London or Berlin") == "Berlin"
    assert normalize_city("Berlin Office") == "Berlin"
    assert normalize_city("DE-Berlin-Trion Building") == "Berlin"
    assert normalize_city("Hinterm Hauptbahnhof 3-5, 76137 Karlsruhe") == "Karlsruhe"
    assert normalize_city("Parsdorf, Bavaria, Germany") == "Parsdorf"
    assert normalize_city("Geeste") == "Geeste"
    assert normalize_city("Remote Germany") == "Remote"
    assert normalize_city("Neu-Ulm") == "Neu-Ulm"
    assert normalize_city("Dublin or Germany") is None
    assert normalize_city("Mapbox Germany") is None
    assert normalize_city("London, UK") is None


def test_abroad_and_generic_locations():
    for loc in ["Paris - full remote", "London or remote within the UK", "France remote", "Remote, UK",
                "Bristol; Edinburgh; London", "Lausanne / hybrid / remote", "Utrecht area, Utrecht, Netherlands"]:
        assert abroad(loc), loc
    for loc in ["Berlin", "London or Berlin", "Geeste", "Remote - Europe timezone"]:
        assert not abroad(loc), loc
    for loc in ["Remote", "Remote job", "EMEA", "Remote - Europe timezone", "Hybrid", "Home Office", "Remote EU", ""]:
        assert generic_location(loc), loc
    for loc in ["Geeste", "Eutin", "Paris, remote", "Berlin"]:
        assert not generic_location(loc), loc


def test_seniority_word_boundaries():
    assert seniority("Senior Google Ads Specialist | International Ecommerce", None) == "senior"
    assert seniority("Lead Financial Services International", None) == "lead"
    assert seniority("Account Manager, Staffing Solutions", 3) == "mid"
    assert seniority("Marketing Intern", None) == "intern"
    assert seniority("Praktikant Marketing (m/w/d)", None) == "intern"
    assert seniority("Werkstudentin Data", None) == "intern"
    assert seniority("Teamleiter Support", None) == "lead"


def test_html_to_text_handles_escaped_html():
    raw = "&lt;p&gt;&lt;strong&gt;About Tensordyne&amp;nbsp;&lt;/strong&gt;&lt;/p&gt;&lt;p&gt;Data &amp;amp; AI&lt;/p&gt;"
    out = html_to_text(raw)
    assert "<" not in out and "&" not in out.replace("Data & AI", "")
    assert "About Tensordyne" in out and "Data & AI" in out
    assert html_to_text("<div><p>L&amp;D budget</p><h2 data-x='1'>Team</h2></div>") == "L&D budget\nTeam"


def test_html_to_text_keeps_bullets():
    out = html_to_text("<p>What you will do</p><ul><li>\n<p>Build APIs</p></li><li>Ship &amp; iterate</li></ul>")
    assert out == "What you will do\n• Build APIs\n• Ship & iterate"


def test_strip_board_boilerplate():
    text = ("We build rockets.\nApply now.\nFind more English Speaking Jobs in Germany on Arbeitnow\n"
            "Find Jobs in United Kingdom on Arbeitnow")
    assert strip_boilerplate(text) == "We build rockets.\nApply now."
    assert strip_boilerplate("Questions? Contact the recruitment department: Jobs in Netherlands on Arbeitnow") == \
        "Questions? Contact the recruitment department:"
    assert strip_boilerplate("We work with Jobs in Germany data.") == "We work with Jobs in Germany data."
