"""Offline tests: a fake IMAP server and a scripted classifier, so no mail or API spend is touched."""


from email.message import EmailMessage


import pytest


import jev_imap_router.core as ms


def make_email(subject, sender="a@b.com", html=None, text="hello", **headers):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "me@example.org", subject
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


class FakeIMAP:
    def __init__(self, folders):
        self.folders = {name: dict(msgs) for name, msgs in folders.items()}
        self.special = {"INBOX.Spam": (b"\\HasNoChildren", b"\\Junk")}
        self.selected = None
        self.flags = {}
        self.moves = []

    def list_folders(self):
        return [(self.special.get(n, (b"\\HasNoChildren",)), b".", n) for n in self.folders]

    def select_folder(self, name):
        self.selected = name
        return {b"UIDVALIDITY": 1}

    def search(self, criteria):
        return list(self.folders[self.selected])

    def fetch(self, uids, parts):
        if parts == ["FLAGS"]:
            return {u: {b"FLAGS": ()} for u in uids if u in self.folders[self.selected]}
        return {u: {b"BODY[]<0>": self.folders[self.selected][u]} for u in uids}

    def move(self, uids, dest):
        for u in uids:
            self.folders[dest][u + 1000] = self.folders[self.selected].pop(u)
            self.moves.append((self.selected, u, dest))

    def add_flags(self, uids, flags):
        for u in uids:
            self.flags[u] = flags

    def create_folder(self, name):
        self.folders[name] = {}

    def subscribe_folder(self, name):
        pass


CATS = [
    ms.Category("Personal", "personal mail", "keep"),
    ms.Category("Action Required", "needs action", "keep", flag=True),
    ms.Category("Newsletters", "newsletters", "move", min_confidence=0.85),
    ms.Category("Junk", "spam", "move", folder="@junk", min_confidence=0.9),
]


BY_NAME = {c.name: c for c in CATS}


class ScriptedClassifier:
    """Answers by subject; a (meta_answer, full_answer) pair scripts the two-stage path."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def classify(self, meta, body):
        stage = "full" if body is not None else "meta"
        self.calls.append((meta["subject"], stage))
        answer = self.script[meta["subject"]]
        if isinstance(answer, list):
            answer = answer[0 if stage == "meta" else 1]
        name, conf, *scam = answer
        return ms.Verdict(BY_NAME[name], conf, 0.01, scam=scam[0] if scam else 0.0)


def make_sorter(tmp_path, folders, script, live=True, budget=5.0):
    fake = FakeIMAP(folders)
    mb = ms.Mailbox.__new__(ms.Mailbox)
    cfg = {"imap": {"inbox": "INBOX"}, "folder_parent": "Sorted", "max_spend_usd_per_day": budget,
           "classifier": {"full_body_below": 0.8, "max_body_chars": 8000, "full_context": False}, "categories": CATS}
    mb.cfg, mb.client, mb.caps, mb.prefix = cfg, fake, {b"MOVE", b"IDLE"}, "INBOX."
    mb.refresh_folders()
    clf = ScriptedClassifier(script)
    return ms.Sorter(cfg, mb, clf, ms.State(tmp_path / "state.json"), live), fake, clf


@pytest.fixture(autouse=True)
def decisions_log(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "DECISIONS_PATH", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(ms, "RUNS_PATH", tmp_path / "runs.jsonl")


def test_parse_prefers_plain_text_and_reads_list_headers():
    raw = make_email("Weekly digest", text="plain body", html="<p>html <b>body</b></p>",
                     List_Id="<news.example.com>", List_Unsubscribe="<mailto:x@y>")
    meta, body = ms.parse_message(raw)
    assert body == "plain body"
    assert meta["list_id"] == "<news.example.com>"
    assert meta["has_list_unsubscribe"] is True
    assert meta["is_reply"] is False


def test_html_only_mail_is_converted_to_text():
    m = EmailMessage()
    m["Subject"] = "x"
    m.set_content("<style>p{}</style><p>Hi&nbsp;there</p><script>evil()</script>", subtype="html")
    _, body = ms.parse_message(m.as_bytes())
    assert body == "Hi there"


def test_inbox_sorting_moves_only_confident_move_categories(tmp_path):
    inbox = {1: make_email("Mom"), 2: make_email("Digest"), 3: make_email("Pay invoice"),
             4: make_email("Maybe digest")}
    script = {"Mom": ("Personal", 0.97), "Digest": ("Newsletters", 0.95),
              "Pay invoice": ("Action Required", 0.9),
              "Maybe digest": [("Newsletters", 0.6), ("Newsletters", 0.7)]}
    sorter, fake, clf = make_sorter(tmp_path, {"INBOX": inbox, "INBOX.Spam": {}}, script)
    stats = sorter.process("INBOX", ["ALL"], 100)

    assert fake.moves == [("INBOX", 2, "INBOX.Sorted.Newsletters")]  # folder created under namespace
    assert fake.flags == {3: [b"\\Flagged"]}
    assert set(fake.folders["INBOX"]) == {1, 3, 4}  # unsure newsletter stays put
    assert ("Maybe digest", "full") in clf.calls  # low confidence triggered a full-body re-read
    assert ("Mom", "full") not in clf.calls
    assert stats["moved"] == 1 and stats["kept"] == 3


def test_second_run_skips_already_sorted_mail(tmp_path):
    sorter, fake, clf = make_sorter(tmp_path, {"INBOX": {1: make_email("Mom")}, "INBOX.Spam": {}},
                                    {"Mom": ("Personal", 0.97)})
    sorter.process("INBOX", ["ALL"], 100)
    sorter.process("INBOX", ["ALL"], 100)
    assert len(clf.calls) == 1


def test_preview_changes_nothing(tmp_path):
    spam = {1: make_email("Mom"), 2: make_email("Digest")}
    script = {"Mom": ("Personal", 0.95), "Digest": ("Newsletters", 0.93)}
    sorter, fake, _ = make_sorter(tmp_path, {"INBOX": {}, "INBOX.Spam": spam}, script, live=False)
    stats = sorter.process("INBOX.Spam", ["ALL"], 100)
    assert fake.moves == [] and fake.flags == {}
    assert "INBOX.Sorted" not in fake.folders
    assert stats["moved"] == 2
    log = (tmp_path / "decisions.jsonl").read_text()
    assert '"moved_to": "INBOX"' in log and '"mode": "preview"' in log


def test_spend_cap_stops_the_run(tmp_path):
    inbox = {i: make_email(f"m{i}") for i in range(1, 11)}
    script = {f"m{i}": ("Personal", 0.95) for i in range(1, 11)}
    sorter, _, clf = make_sorter(tmp_path, {"INBOX": inbox, "INBOX.Spam": {}}, script, budget=0.035)
    stats = sorter.process("INBOX", ["ALL"], 100)
    assert len(clf.calls) == 4 and stats["checked"] == 4  # 4 x $0.01 crosses $0.035


def test_generated_config_loads(tmp_path):
    from jev_imap_router import onboarding
    path = tmp_path / "config.yaml"
    path.write_text(onboarding.build_config("alex@example.org", "imap.example.org", 993, "founder"))
    cfg = ms.load_config(path)
    assert cfg["mode"] == "preview"
    names = [c.name for c in cfg["categories"]]
    assert names[0] == "Action Required" and names[-1] == "Review" and "Junk" in names


def test_jev_request_and_answer_parsing():
    import json as _json

    import httpx2
    from typesafe_sdk import TypeSafeClient

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = _json.loads(request.content)
        return httpx2.Response(200, json={
            "model": "jev-1.13.0",
            "answers": {"category": {"type": "choice", "choice": "Newsletters", "confidence": 0.91,
                                     "probabilities": {c.name: (0.94 if c.name == "Newsletters" else 0.02)
                                                       for c in CATS}},
                        "scam": {"type": "noul", "noul": 0.03}},
            "usage": {"input_tokens": 1000, "output_tokens": 5},
        })

    clf = ms.JevClassifier("jev-latest", CATS, "test-key")
    clf.client = TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler))
    v = clf.classify({"subject": "Weekly digest"}, None)

    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    q = seen["body"]["questions"]["category"]
    assert q["type"] == "choice" and set(q["criteria"]) == {c.name for c in CATS}
    assert seen["body"]["state"]["evidence_stage"] == "metadata_only"
    assert seen["body"]["questions"]["scam"]["type"] == "noul"
    assert v.category.name == "Newsletters" and v.confidence == 0.91 and v.scam == 0.03
    assert v.cost_usd == pytest.approx(1000 * 0.042 / 1e6)


def test_runs_are_recorded_with_timing_and_cost(tmp_path):
    import json as _json
    inbox = {1: make_email("Mom"), 2: make_email("Maybe digest")}
    script = {"Mom": ("Personal", 0.97), "Maybe digest": [("Newsletters", 0.6), ("Newsletters", 0.9)]}
    sorter, _, _ = make_sorter(tmp_path, {"INBOX": inbox, "INBOX.Spam": {}}, script)
    sorter.process("INBOX", ["ALL"], 100, "backfill")
    run = _json.loads((tmp_path / "runs.jsonl").read_text())
    assert run["command"] == "backfill" and run["checked"] == 2 and run["jev_calls"] == 3
    assert run["stages"] == {"metadata": 1, "full_body": 1}
    assert run["cost"] == pytest.approx(0.03) and run["seconds"] >= 0
    decision = _json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[0])
    assert {"latency_ms", "input_tokens", "cost", "jev_calls"} <= set(decision)


def test_sender_checks_catch_a_spoofed_voicemail():
    m = EmailMessage()
    m["From"] = '"VoiceMail | example.org" <vm-alex@servermail.com>'
    m["Subject"] = "New Voice Message"
    m["Authentication-Results"] = "relay.example; dkim=pass header.d=servermail.com header.s=x; spf=pass smtp.mailfrom=servermail.com"
    m["X-Recommended-Action"] = "reject"
    m.set_content("Listen: https://evil-audio.xyz/play?id=1")
    m.add_alternative('<a href="https://evil-audio.xyz/play">Play</a>', subtype="html")
    meta, _ = ms.parse_message(m.as_bytes())
    checks = meta["sender_checks"]
    assert checks["display_name_claims_other_domain"] == ["example.org"]
    assert checks["link_domains"] == ["evil-audio.xyz"] and checks["links_match_sender"] is False
    assert checks["from_domain_signed_by_itself"] is True and checks["spf"] == "pass"
    assert "reject" not in str(meta)  # the provider's own verdict is never shown to Jev


def test_voicemail_spoof_claiming_recipient_domain_is_a_hard_flag():
    flags = _flags('"VoiceMail | example.org" <vm-alex@servermail.com>', "New Voice Message",
                   Delivered_To="alex@example.org")
    assert "display_name_claims_recipient_domain" in flags


def test_sender_checks_for_a_legit_newsletter():
    m = EmailMessage()
    m["From"] = "Plaid <info@email.plaid.com>"
    m["Authentication-Results"] = "relay; dkim=pass header.d=plaid.com header.s=s1; dmarc=pass"
    m.set_content("Read more at https://plaid.com/blog and https://email.plaid.com/x")
    meta, _ = ms.parse_message(m.as_bytes())
    c = meta["sender_checks"]
    assert c["from_domain_signed_by_itself"] is True and c["links_match_sender"] is True and c["dmarc"] == "pass"


def test_full_context_mode_sends_body_in_one_call(tmp_path):
    sorter, _, clf = make_sorter(tmp_path, {"INBOX": {1: make_email("Maybe digest")}, "INBOX.Spam": {}},
                                 {"Maybe digest": [("Newsletters", 0.6), ("Newsletters", 0.95)]})
    sorter.full_context = True
    sorter.process("INBOX", ["ALL"], 100)
    assert clf.calls == [("Maybe digest", "full")]


def _flags(from_, subject="Hello", body="hi", html=None, **headers):
    m = EmailMessage()
    m["From"], m["Subject"] = from_, subject
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return ms.parse_message(m.as_bytes())[0]["sender_checks"].get("red_flags", [])


@pytest.mark.parametrize("from_,subject,html,expected", [
    ("Capital One <cap@secure.net>", "Do you recognize this purchase?", None, "brand_impersonation"),
    ('"WellsFargo" <wellsfargo.alerts@secure.net>', "Alert on your Account", None, "brand_impersonation"),
    ("Chase Alerts <no-reply@chs-secure.com>", "Review dispute", None, "brand_impersonation"),
    ("Facebook <support@zenciala.sbs>", "New login", None, "risky_sender_tld"),
    ("Amazon Security <alerts@amaz0n-verify.com>", "Verify your account", None, "brand_impersonation"),
    ("Pamela <pamela@lender.biz>", "Re: Could Acme access capital?", None, "fake_reply_no_thread"),
])
def test_red_flags_catch_phishing_patterns(from_, subject, html, expected):
    assert expected in _flags(from_, subject, html=html)


@pytest.mark.parametrize("from_,subject", [
    ("Chase Smith <chase@sigmachi.org>", "Dues question"),          # a person named Chase
    ("Capital One <capitalone@notification.capitalone.com>", "Your statement"),
    ("Google <no-reply@accounts.google.com>", "Security alert"),
    ("Allen via Docusign <dse_na2@docusign.net>", "Completed: Documents"),
    ("Zoom <teamzoom@zoom.com>", "What's new"),
    ("Amazon Web Services <invoicing@aws.com>", "Billing Statement Available"),
    ('"Accounts Receivable (accounts-receivable@plaid.com)" <billing@stripe.com>', "Thank you for your payment"),
])
def test_red_flags_leave_real_senders_alone(from_, subject):
    assert not ms.HARD_FLAGS & set(_flags(from_, subject))


def test_filing_uses_summed_folder_probability():
    sorter = ms.Sorter.__new__(ms.Sorter)
    sorter.cfg = {"categories": CATS + [ms.Category("Greek Life", "g", "move", min_confidence=0.85)]}
    torn_between_folders = ms.Verdict(BY_NAME["Newsletters"], 0.5, 0,
                                      probabilities={"Newsletters": 0.55, "Greek Life": 0.40, "Personal": 0.05})
    maybe_personal = ms.Verdict(BY_NAME["Newsletters"], 0.7, 0,
                                probabilities={"Newsletters": 0.75, "Personal": 0.25})
    unsure_junk = ms.Verdict(BY_NAME["Junk"], 0.95, 0, scam=0.2, probabilities={"Junk": 1.0})
    assert sorter.confident_move(torn_between_folders) is True
    assert sorter.confident_move(maybe_personal) is False
    assert sorter.confident_move(unsure_junk) is False


@pytest.mark.parametrize("meta,expected", [
    ({"subject": "Re: Acme 20 Minute Demo", "is_reply": True}, True),         # prospect replying
    ({"subject": "Fw: Acme Payout On Its Way"}, True),                         # customer forwarding
    ({"subject": "Anything", "you_replied": True}, True),
    ({"subject": "RE: Bennett"}, False),                                          # fake reply, no thread headers
    ({"subject": "Re: webinar", "is_reply": True, "has_list_unsubscribe": True}, False),  # bulk
])
def test_human_thread(meta, expected):
    assert ms.human_thread(meta) is expected


def test_human_threads_stay_in_inbox(tmp_path):
    inbox = {1: make_email("Re: demo", In_Reply_To="<x@y>"), 2: make_email("Digest")}
    sorter, fake, _ = make_sorter(tmp_path, {"INBOX": inbox, "INBOX.Spam": {}},
                                  {"Re: demo": ("Newsletters", 0.99), "Digest": ("Newsletters", 0.99)})
    fake.fetch_flags = {}
    sorter.process("INBOX", ["ALL"], 100)
    assert [u for _, u, _ in fake.moves] == [2]


def test_html_inside_plain_part_is_cleaned():
    m = EmailMessage()
    m["Subject"] = "Your Airtable statement"
    m.set_content('Your <a href="https://airtable.com/x">invoice</a> is ready.<br/><br/>Best,<br/>The Airtable Team')
    _, body = ms.parse_message(m.as_bytes())
    assert "<a" not in body and "href" not in body and "invoice is ready." in body.replace("  ", " ")


def test_out_of_credits_stops_instead_of_skipping():
    err = type("E", (Exception,), {"status": 402})()
    with pytest.raises(SystemExit, match="out of credits"):
        ms.fatal_typesafe(err)
    ms.fatal_typesafe(type("E", (Exception,), {"status": 500})())   # ordinary errors don't stop the run

