---
name: jev-imap-router
description: Set up jev-imap-router and design email sorting categories for it (IMAP + Jev). Use when the user wants their inbox sorted with jev-imap-router, or wants to set up, customize, or fix its categories.
---

# Set up jev-imap-router

These instructions are for a coding agent (Claude Code, Codex, Cursor or similar) helping someone set
up jev-imap-router. It sorts their email into folders using Jev, TypeSafe's classifier model.

Work through the steps in order. Explain what you're doing in plain language as you go. Keep it
simple for them: do the work yourself and only ask them for things you can't do.

Ground rules:
- Their password and API key must never pass through you. They enter those themselves in step 3.
- Don't set `mode: live` or run `backfill` or `install-agent` until they say so in step 6.
  Until then everything is a preview and nothing in their mailbox changes.
- Their email stays on this machine. Don't paste email contents anywhere outside this session.

## 1. Install

Check for uv with `uv --version`. If it's missing, ask them first, then install it:
`curl -LsSf https://astral.sh/uv/install.sh | sh`

Then install jev-imap-router:
`uv tool install jev-imap-router`
If that isn't found, use `uv tool install git+https://github.com/bquigley1/jev-imap-router`.

Check it worked with `jev-imap-router --version`.

## 2. Create their config

Ask for the email address they want sorted. Then run:
`jev-imap-router init --email THEIR_ADDRESS --preset universal --no-login`

This fills in their mail server and writes `~/.jev-imap-router/config.yaml`. If it can't detect the
server, ask them for it (their provider's IMAP settings page lists it) and add `--host HOST`.

## 3. Have them log in

Ask them to open a separate terminal window and run:
`jev-imap-router login`

It asks for two things with hidden typing, and gives provider-specific help:
1. An app password for their email. Gmail, iCloud, Outlook.com and Yahoo require one.
2. A TypeSafe API key from https://console.typesafe.ai/keys (they'll need to add a few dollars of credit).

Wait until they tell you it printed "Logged in". If it failed, help them with the app password.

## 4. Design categories that fit their mail

Run `jev-imap-router discover --days 60`, then read `~/.jev-imap-router/logs/discover.md`. It's a
table of who emails them, how much of it is bulk mail, and what they reply to. Only open
`logs/sample.jsonl` if you need specifics. Tell them in a few sentences what their mail is mostly about.

Then propose categories and ask them to confirm before you edit `config.yaml`:
- Inbox categories (`action: keep`) for mail they need to see: real people, customers, things
  needing action. Flag the "needs action" one with `flag: true`. Keep a fallback called "Review".
- Filing categories (`action: move`) for high-volume automated mail: receipts, newsletters,
  notifications, promotions, calendar, travel, cold outreach, and anything big and specific to them
  such as their own product's automated emails, lead alerts or a hobby.
- Keep "Junk" with `folder: "@junk"` and `min_confidence: 0.90`.
- Aim for 8 to 16 categories in total.
- Write each `when` as literal inclusions and exclusions that name real senders from their mail, for
  example "Stripe, GitHub and AWS receipts" or "Excludes marketing from companies they already use".
  Jev reads instructions literally, so say exactly what you mean.

## 5. Preview and refine

Run `jev-imap-router preview`, then `jev-imap-router review`, and read the output. It shows where
mail would go, each folder's top senders, the moves worth a second look, and low-confidence decisions.

Fix what's wrong, then preview again. Two or three rounds is usually enough.
- If a sender lands in the wrong folder, tighten the `when` text of both categories involved.
- If real people or conversations are being filed, strengthen the wording of the Inbox categories.
  Conversations they've replied to are already protected automatically.
- If a lot of mail stays in the Inbox with low confidence between two folders, the two descriptions
  overlap. Make them distinct.
- If anything important is headed to Spam, stop and show them.

## 6. Hand off

Summarize the final categories, what the last preview would do (counts per folder), anything still
uncertain, and the cost so far (`jev-imap-router stats --include-preview`).

Then ask whether they want to turn it on. If they say yes:
1. Set `mode: live` in `~/.jev-imap-router/config.yaml`.
2. Run `jev-imap-router backfill --limit 5000` to sort existing mail, newest first.
3. Run `jev-imap-router install-agent` so new mail is sorted as it arrives (macOS). On Linux, suggest
   running `jev-imap-router watch` under systemd.
