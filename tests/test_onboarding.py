"""Setup and category-design commands: providers, presets, init, discover summary, review."""

import argparse
import json

import pytest

import jev_imap_router.core as core
from jev_imap_router import onboarding, providers


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(core, "DECISIONS_PATH", tmp_path / "logs" / "decisions.jsonl")
    (tmp_path / "logs").mkdir()
    return tmp_path


@pytest.mark.parametrize("address,host", [
    ("someone@gmail.com", "imap.gmail.com"),
    ("someone@icloud.com", "imap.mail.me.com"),
    ("someone@hotmail.com", "outlook.office365.com"),
    ("someone@fastmail.com", "imap.fastmail.com"),
])
def test_provider_by_domain(address, host):
    assert providers.guess(address).host == host


def test_custom_domain_uses_mx_record(monkeypatch):
    import dns.resolver

    class MX:
        exchange = "aspmx.l.google.com."
    monkeypatch.setattr(dns.resolver, "resolve", lambda *a, **k: [MX()])
    assert providers.guess("founder@startup.example") is providers.GMAIL


def test_unknown_domain_returns_none(monkeypatch):
    import dns.resolver

    def fail(*a, **k):
        raise dns.resolver.NXDOMAIN()
    monkeypatch.setattr(dns.resolver, "resolve", fail)
    assert providers.guess("x@nowhere.invalid") is None


@pytest.mark.parametrize("name", onboarding.PRESETS)
def test_every_preset_is_complete(name):
    p = onboarding.preset(name)
    names = [c["name"] for c in p["categories"]]
    assert len(names) == len(set(names)), "duplicate category names"
    assert names[-1] == "Review"
    junk = next(c for c in p["categories"] if c["name"] == "Junk")
    assert junk["folder"] == "@junk" and junk["action"] == "move"
    assert any(c["action"] == "keep" and c.get("flag") for c in p["categories"]), "no flagged Inbox category"
    for c in p["categories"]:
        assert c["action"] in ("keep", "move") and len(c["when"]) > 40


def test_init_writes_a_loadable_config(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(onboarding.keyring, "set_password", lambda svc, k, v: saved.__setitem__(k, v))
    monkeypatch.setattr(onboarding.getpass, "getpass", lambda prompt: "app-password")
    monkeypatch.setattr(core, "secret", lambda *a: "existing-key")
    path = tmp_path / "config.yaml"
    args = argparse.Namespace(config=path, force=False, email="alex@gmail.com", host=None, port=None,
                              preset="sales", no_test=True)
    onboarding.cmd_init(None, args)
    cfg = core.load_config(path)
    assert cfg["imap"]["host"] == "imap.gmail.com" and cfg["imap"]["username"] == "alex@gmail.com"
    assert cfg["mode"] == "preview"
    assert "Hot Lead" in [c.name for c in cfg["categories"]]
    assert saved == {"imap:alex@gmail.com": "app-password"}
    assert "password" not in path.read_text().lower().replace("passwords and api keys", "")


def test_init_refuses_to_overwrite(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mode: live\n")
    args = argparse.Namespace(config=path, force=False, email="a@gmail.com", host=None, port=None,
                              preset="universal", no_test=True)
    with pytest.raises(SystemExit, match="already exists"):
        onboarding.cmd_init(None, args)


def test_discover_summary():
    rows = [{"from": "Stripe <receipts@stripe.com>", "subject": f"Receipt #{i}", "bulk": False, "replied": False}
            for i in range(5)]
    rows += [{"from": "Pat <pat@client.example>", "subject": "Re: project", "bulk": False, "replied": True}]
    text = onboarding.summarize_sample(rows)
    assert "6 unique emails" in text and "| 5 | stripe.com |" in text and "R client.example" in text


def test_review_summarizes_last_preview(home, capsys):
    decisions = [
        {"mode": "preview", "command": "backfill", "uid": 1, "from": "Meta <x@facebookmail.com>", "subject": "Receipt",
         "category": "Receipts & Billing", "confidence": 0.99, "moved_to": "Sorted/Receipts & Billing"},
        {"mode": "preview", "command": "backfill", "uid": 2, "from": "Pat <pat@gmail.com>", "subject": "hey",
         "category": "Newsletters & Events", "confidence": 0.9, "moved_to": "Sorted/Newsletters & Events"},
        {"mode": "preview", "command": "backfill", "uid": 3, "from": "Sam <sam@co.example>", "subject": "Re: hi",
         "category": "People", "confidence": 0.95, "moved_to": None, "protected": True},
        {"mode": "live", "command": "backfill", "uid": 4, "from": "x@y.z", "subject": "ignored",
         "category": "People", "confidence": 1.0, "moved_to": None},
    ]
    core.DECISIONS_PATH.write_text("\n".join(json.dumps(d) for d in decisions))
    onboarding.cmd_review(None, argparse.Namespace(last=2000))
    out = capsys.readouterr().out
    assert "3 emails" in out
    assert "Kept as real conversations (never filed): 1" in out
    assert "Sorted/Newsletters & Events <- Newsletters & Events (0.90) Pat <pat@gmail.com>" in out  # personal address moved


def test_agent_prompt_ships_with_package(capsys):
    onboarding.cmd_agent_prompt(None, None)
    out = capsys.readouterr().out
    assert "discover" in out and "preview" in out and "Never switch `mode` to `live`" in out


def test_hard_red_flag_counts_as_scam_evidence_for_junk():
    junk = core.Category("Junk", "spam", "move", folder="@junk", min_confidence=0.9)
    sorter = core.Sorter.__new__(core.Sorter)
    sorter.cfg = {"categories": [junk]}
    borderline = core.Verdict(junk, 0.95, 0, scam=0.3, probabilities={"Junk": 1.0})
    assert sorter.confident_move(borderline) is False
    borderline.red_flags = ["brand_impersonation"]
    assert sorter.confident_move(borderline) is True
