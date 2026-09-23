"""First-run setup and category design: init, discover, preview, review, agent-prompt."""

from __future__ import annotations

import collections
import getpass
import json
import re
import sys
from importlib import resources
from pathlib import Path

import keyring
import yaml

from . import core, providers

PRESETS = ("universal", "founder", "sales", "freelancer")

SETTINGS = {
    "mode": "preview",
    "folder_parent": "Sorted",
    "lookback_days": 2,
    "max_per_run": 100,
    "max_spend_usd_per_day": 2.00,
    "classifier": {"model": "jev-latest", "full_context": True, "max_body_chars": 12000, "concurrency": 8,
                   "full_body_below": 0.80},
}

HEADER = """\
# jev-imap-router config. Categories are plain English: `when` says what belongs there.
#   action: keep -> stays in the Inbox (flag: true adds the Mail flag)
#   action: move -> filed to <folder_parent>/<name> when Jev is confident (min_confidence);
#                   anything uncertain stays in the Inbox. folder: "@junk" = the server's Junk/Spam.
# mode: preview logs what would happen and changes nothing. Switch to live when you're happy.
# Passwords and API keys are in your system keychain, never in this file.
"""


def preset(name: str) -> dict:
    """A preset's own (Inbox) categories plus the shared filing folders, with Review kept last."""
    pkg = resources.files("jev_imap_router.presets")
    own = yaml.safe_load(pkg.joinpath(f"{name}.yaml").read_text())
    filing = yaml.safe_load(pkg.joinpath("filing.yaml").read_text())["categories"]
    cats = [c for c in own["categories"] if c["name"] != "Review"]
    names = {c["name"] for c in cats}
    cats += [c for c in filing if c["name"] not in names]
    cats += [c for c in own["categories"] if c["name"] == "Review"]
    return {"name": own["name"], "summary": own["summary"], "categories": cats}


def build_config(address: str, host: str, port: int, preset_name: str) -> str:
    cfg = {"imap": {"host": host, "port": port, "username": address, "inbox": "INBOX"}, **SETTINGS,
           "categories": preset(preset_name)["categories"]}
    return HEADER + "\n" + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=100)


def ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def cmd_init(_cfg, args) -> None:
    """Interactive setup: IMAP login, TypeSafe key, starting categories."""
    path: Path = args.config
    print("jev-imap-router setup\n")
    if path.exists() and not args.force:
        sys.exit(f"{path} already exists. Edit it directly, or run `init --force` to start over.")
    address = args.email or ask("Your email address")
    guess = providers.guess(address)
    if guess:
        print(f"Looks like {guess.name}.")
    scripted = bool(args.email)  # flags given: take detected settings instead of prompting
    host = args.host or (guess.host if guess and scripted else ask("IMAP server", guess.host if guess else ""))
    port = int(args.port or (guess.port if guess and scripted else ask("IMAP port", str(guess.port if guess else 993))))
    if guess and guess.password_help:
        print(f"\nPassword: {guess.password_help}")
    password = getpass.getpass(f"IMAP password for {address} (hidden): ")
    keyring.set_password(core.KEYRING_SERVICE, f"imap:{address}", password)
    if not core.secret("typesafe-api-key", "TYPESAFE_API_KEY"):
        print("\nJev runs on TypeSafe's API. Create a key at https://console.typesafe.ai/keys")
        key = getpass.getpass("TypeSafe API key (hidden): ").strip()
        if key:
            keyring.set_password(core.KEYRING_SERVICE, "typesafe-api-key", key)

    print("\nStarting categories (you can change them any time):")
    for i, name in enumerate(PRESETS, 1):
        p = preset(name)
        print(f"  {i}. {p['name']}: {p['summary']}")
    print(f"  {len(PRESETS) + 1}. Let my coding agent design them from my mail (starts from Universal)")
    choice = args.preset or ask("Choose", "1")
    agent = choice == str(len(PRESETS) + 1)
    name = "universal" if agent else (choice if choice in PRESETS else PRESETS[int(choice) - 1])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_config(address, host, port, name))
    print(f"\nWrote {path}")
    if not args.no_test:
        print("Testing the login...")
        cfg = core.load_config(path)
        mb = core.Mailbox(cfg)
        print(f"Logged in. Spam folder: {mb.junk_folder() or 'not found'}. "
              f"Inbox: {mb.client.folder_status(mb.inbox, [b'MESSAGES'])[b'MESSAGES']} messages.")
        mb.close()
    print("\nNext:")
    if agent:
        print("  1. Open your coding agent (Claude Code, Cursor, Codex, ...) and paste the prompt from:")
        print("       jev-imap-router agent-prompt")
    else:
        print("  1. jev-imap-router preview      # classify recent mail, change nothing")
        print("  2. jev-imap-router review       # see where everything would go")
    print(f"  Then set `mode: live` in {path} and run `jev-imap-router backfill`, then `install-agent`.")


def cmd_discover(cfg, args) -> None:
    """Export recent mail (headers + snippets) and a sender summary for designing categories."""
    core.cmd_sample(cfg, args)
    rows = [json.loads(line) for line in (core.LOG_DIR / "sample.jsonl").open()]
    out = core.LOG_DIR / "discover.md"
    out.write_text(summarize_sample(rows))
    print(f"Summary for you or your agent: {out}")


def summarize_sample(rows: list[dict]) -> str:
    def dom(f: str) -> str:
        m = re.search(r"@([\w.-]+)", f or "")
        return m.group(1).lower() if m else "?"

    by = collections.defaultdict(list)
    for r in rows:
        by[dom(r.get("from", ""))].append(r)
    total = len(rows)
    bulk = sum(r.get("bulk", False) for r in rows)
    replied = sum(r.get("replied", False) for r in rows)
    lines = [f"# Mail sample: {total} unique emails",
             f"{bulk} bulk (newsletters/marketing), {replied} you replied to.\n",
             "| emails | sender domain | bulk | replied | example subjects |", "|---:|---|---:|---:|---|"]
    for d, rs in sorted(by.items(), key=lambda kv: -len(kv[1]))[:80]:
        subj = "; ".join(dict.fromkeys((r.get("subject") or "")[:50] for r in rs))
        lines.append(f"| {len(rs)} | {d} | {sum(r.get('bulk', False) for r in rs)} | "
                     f"{sum(r.get('replied', False) for r in rs)} | {subj[:160].replace('|', '/')} |")
    tail = [r for d, rs in by.items() if len(rs) <= 2 for r in rs]
    lines += [f"\n## Long tail: {len(tail)} emails from {sum(1 for rs in by.values() if len(rs) <= 2)} rare senders",
              *(f"- {'R ' if r.get('replied') else ''}{dom(r.get('from', ''))}: {(r.get('subject') or '')[:70]}"
                for r in tail[:60])]
    return "\n".join(lines) + "\n"


def cmd_preview(cfg, args) -> None:
    """Classify recent Inbox mail without changing anything (re-evaluates after config edits)."""
    state = core.State()
    for f in state.data["folders"].values():
        f["previewed"] = []
    state.save()
    args.dry_run, args.days = True, None
    core.cmd_backfill(cfg, args)
    print("Run `jev-imap-router review` to see where everything would go.")


def cmd_review(_cfg, args) -> None:
    """Readable summary of the last preview: per folder, top senders, and the moves worth a second look."""
    if not core.DECISIONS_PATH.exists():
        sys.exit("No decisions yet. Run `jev-imap-router preview` first.")
    rows = [json.loads(line) for line in core.DECISIONS_PATH.open()]
    rows = [r for r in rows if r.get("mode") == "preview" and r.get("command") in ("backfill", "run")]
    latest = {}
    for r in rows:
        latest[r["uid"]] = r
    rows = list(latest.values())[-args.last:]
    if not rows:
        sys.exit("No preview decisions found. Run `jev-imap-router preview` first.")

    def dom(f: str) -> str:
        m = re.search(r"@([\w.-]+)", f or "")
        return m.group(1).lower() if m else "?"

    out = [f"# Preview review: {len(rows)} emails\n"]
    dest = collections.Counter(r["moved_to"] or "(stays in Inbox)" for r in rows)
    out += ["| emails | goes to |", "|---:|---|", *(f"| {n} | {d} |" for d, n in dest.most_common())]
    stay = collections.Counter(r["category"] for r in rows if not r["moved_to"])
    out.append("\nStaying in Inbox by category: " + ", ".join(f"{c} ({n})" for c, n in stay.most_common()))
    out.append(f"Kept as real conversations (never filed): {sum(1 for r in rows if r.get('protected'))}")
    out.append("\n## Each folder's top senders")
    for folder in sorted({r["moved_to"] for r in rows if r["moved_to"]}):
        c = collections.Counter(dom(r["from"]) for r in rows if r["moved_to"] == folder)
        out.append(f"- **{folder}** ({sum(c.values())}): " + ", ".join(f"{d} ({n})" for d, n in c.most_common(8)))
    personal = {"gmail.com", "yahoo.com", "outlook.com", "icloud.com", "hotmail.com", "aol.com", "me.com"}
    risky = [r for r in rows if r["moved_to"] and (dom(r["from"]) in personal or r["moved_to"] in ("Spam", "Junk"))]
    out.append(f"\n## Worth a second look ({len(risky)}): moves from personal addresses, and anything going to Spam")
    out += [f"- {r['moved_to']} <- {r['category']} ({r['confidence']:.2f}) {r['from'][:40]}: {r['subject'][:60]}"
            for r in risky[:40]]
    unsure = [r for r in rows if not r["moved_to"] and not r.get("protected") and r["confidence"] < 0.6]
    out.append(f"\n## Low confidence, left in the Inbox ({len(unsure)}): candidates for clearer category wording")
    out += [f"- {r['category']} ({r['confidence']:.2f}) {r['from'][:40]}: {r['subject'][:60]}" for r in unsure[:30]]
    text = "\n".join(out) + "\n"
    (core.LOG_DIR / "review.md").write_text(text)
    print(text)


def cmd_agent_prompt(_cfg, _args) -> None:
    print(resources.files("jev_imap_router").joinpath("agent_prompt.md").read_text())
