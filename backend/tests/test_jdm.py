"""JustDeleteMe-Integration: tatsächliche Datenstruktur, keine erfundenen Links."""
from __future__ import annotations

import json
from pathlib import Path

from app.jdm.catalog import load_catalog, get_catalog
from app.models import Service

DATA = Path(__file__).resolve().parents[1] / "app" / "data" / "jdm"


def test_vendored_data_structure():
    raw = json.loads((DATA / "sites.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list) and len(raw) > 2000
    for item in raw:
        assert {"name", "url", "difficulty", "domains"} <= item.keys()
        assert item["difficulty"] in {"easy", "medium", "hard", "impossible", "limited"}
        assert isinstance(item["domains"], list)
    version = json.loads((DATA / "VERSION.json").read_text())
    assert len(version["commit"]) == 40
    assert "MIT" in (DATA / "LICENSE").read_text()


def test_catalog_urls_are_copied_verbatim():
    raw = {e["name"].strip(): e for e in json.loads((DATA / "sites.json").read_text(encoding="utf-8"))}
    cat = get_catalog()
    assert len(cat) >= len(raw) - 5
    for entry in cat.entries:
        assert entry.url == raw[entry.name]["url"].strip()
        assert entry.url.startswith(("https://", "http://"))


def test_catalog_rejects_unsafe_entries(tmp_path):
    (tmp_path / "sites.json").write_text(json.dumps([
        {"name": "Böse", "url": "javascript:alert(1)", "difficulty": "easy", "domains": ["boese.example"]},
        {"name": "Kaputt", "url": "https://ok.example", "difficulty": "unbekannt", "domains": ["k.example"]},
        {"name": "Userinfo", "url": "https://user@evil.example", "difficulty": "easy", "domains": ["u.example"]},
        {"name": "Gut", "url": "https://gut.example/delete", "difficulty": "hard", "domains": ["gut.example"],
         "email": "nicht eine adresse", "notes_de": "Support anschreiben"},
    ]))
    cat = load_catalog(tmp_path)
    assert [e.name for e in cat.entries] == ["Gut"]
    gut = cat.entries[0]
    assert gut.email is None and gut.instructions == "Support anschreiben"


def test_api_exposes_jdm_link_only_for_catalog_matches(auth, db, user):
    db.add_all([
        Service(user_id=user.id, key="jdm:GitHub", display_name="GitHub", jdm_name="GitHub", domains=["github.com"],
                sources={}, signals={}, confidence=0.9, memory={"welcome": {"count": 1, "best": 0.9}}),
        Service(user_id=user.id, key="domain:baeckerei-muster.at", display_name="Baeckerei-Muster", jdm_name=None,
                domains=["baeckerei-muster.at"], sources={}, signals={}, confidence=0.5,
                memory={"order": {"count": 1, "best": 0.5}}),
    ])
    db.commit()
    items = {s["name"]: s for s in auth.get("/api/services").json()}
    gh = get_catalog().by_name("GitHub")
    assert items["GitHub"]["jdm"]["url"] == gh.delete_url
    assert items["GitHub"]["jdm"]["difficulty"] == gh.difficulty
    assert items["Baeckerei-Muster"]["jdm"] is None


def test_csv_export_escapes_formulas(auth, db, user):
    db.add(Service(user_id=user.id, key="domain:x.example", display_name="=HYPERLINK(\"http://evil\")", jdm_name=None,
                   domains=["x.example"], sources={}, signals={}, confidence=0.5,
                   memory={"welcome": {"count": 1, "best": 0.5}}))
    db.commit()
    r = auth.get("/api/services/export.csv")
    assert r.status_code == 200 and "'=HYPERLINK" in r.text
