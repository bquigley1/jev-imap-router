# jev-imap-router

AI inbox sorting for any IMAP mailbox: Gmail, iCloud, Fastmail, Outlook.com, Yahoo, or your own domain.

You describe your categories in plain English. [Jev](https://docs.typesafe.ai/introduction) reads each
email and picks one. The email is filed on your mail server, so Apple Mail, Outlook, your phone, and
webmail all see the same folders. Nothing is ever deleted.

```
Inbox (what you actually need to see)       Sorted/
  Action Required  ⚑                          Receipts & Billing
  Customers                                   Newsletters & Events
  People                                      Notifications
  Review (Jev wasn't sure)                    Promotions & Social
                                              Cold Outreach
                                              ...        Junk -> your Spam folder
```

## Quick start

You need Python 3.11+ with [uv](https://docs.astral.sh/uv/), an IMAP app password for your mailbox,
and a TypeSafe API key from [console.typesafe.ai](https://console.typesafe.ai/keys).

```sh
uv tool install jev-imap-router      # or run anything below with `uvx jev-imap-router ...`
jev-imap-router init                 # email, password, API key, starting categories
jev-imap-router preview              # classify your 300 most recent emails, move nothing
jev-imap-router review               # where would everything go?
```

When the review looks right, set `mode: live` in `~/.jev-imap-router/config.yaml`, then:

```sh
jev-imap-router backfill --limit 5000    # sort existing mail, newest first
jev-imap-router install-agent            # keep sorting new mail as it arrives (macOS)
```

`init` fills in the IMAP server for Gmail, iCloud, Outlook.com, Yahoo, Fastmail, AOL, Zoho, Proton
(via Bridge), and Namecheap Private Email. For custom domains it checks your MX record. Passwords and
API keys go in your system keychain, never in the config file.

## Choosing your categories

There are three ways, and you can switch any time:

**1. Presets.** `init` offers Universal, Founder/operator, Sales, and Freelancer/creator. Each is a set
of Inbox categories for that role, plus shared filing folders (receipts, newsletters, notifications,
promotions, calendar, travel, cold outreach, junk).

**2. Let your coding agent design them from your mail.** This gives the best results. Run
`jev-imap-router agent-prompt` and paste the output into Claude Code, Cursor, Codex, or any agent that
can run commands. The agent will:

1. run `discover`, which summarizes who emails you (locally, no AI involved)
2. propose categories that fit your mail, and ask you to confirm them
3. run `preview` and `review`, then fix the categories that misfile, two or three rounds
4. stop before anything goes live

For Claude Code, you can install it as a skill instead:
`cp -r agent/skills/jev-imap-router ~/.claude/skills/`

**3. Write them yourself.** Categories live in `config.yaml`:

```yaml
- name: Receipts & Billing
  when: >-
    Receipts, invoices, and payment confirmations when there's no problem to fix,
    including Stripe, GitHub, and AWS receipts. Problems are Action Required.
  action: move            # keep = stays in Inbox, move = filed under Sorted/
  min_confidence: 0.85
```

Jev reads `when` literally, so name real senders and spell out exclusions. It handles up to 255
categories per request, but 8 to 16 clear ones work best.

## How it decides

- **One call per email, full context.** Jev gets the headers, the body text (up to 12,000 characters),
  and sender checks computed in code: whether the sender's own domain signed the email (DKIM/SPF/DMARC),
  whether the display name claims another brand or your own domain ("VoiceMail | yourdomain.com"),
  where the links really point, lookalike and throwaway domains, risky attachment types, and fake
  "Re:" threads. Your provider's own spam verdict is deliberately left out, so Jev doesn't just copy it.
- **Confidence decides what moves.** A category only files mail when Jev is confident. If it's torn
  between two filing folders (say, Newsletters vs Promotions), it still files by adding up those
  probabilities. If there's a real chance the email is personal or needs action, it stays in the Inbox.
- **Conversations are protected.** Anything you've replied to, and any real reply or forward
  (with genuine threading headers), is never filed, whatever Jev says.
- **Junk is strict.** Mail goes to Spam only when Jev picks Junk *and* either rates it as likely a scam
  or it carries a clear red flag (brand impersonation, your own domain in a stranger's name), because
  many providers' spam filters learn from what you move there.
- **Preview first, always.** New configs start in `mode: preview`, and every decision is logged to
  `~/.jev-imap-router/logs/decisions.jsonl`.

## Cost and speed

Jev bills input tokens only ($0.042 per million at the time of writing). On one real mailbox of
about 11,000 emails, full-context classification cost **about $0.14 per 1,000 emails** and ran at
**about 200 emails a minute** (157 ms median per Jev call, 8 in parallel; downloading mail was the
bottleneck). `max_spend_usd_per_day` in the config is a hard stop, $2.00 by default.
`jev-imap-router stats` shows your own numbers.

## Privacy

Mail content is sent to TypeSafe's API for classification: headers and up to 12,000 characters of
text per email. See [TypeSafe's data handling](https://docs.typesafe.ai/models). Nothing else leaves
your machine. `discover` samples stay in `~/.jev-imap-router/logs/`.

## Limitations

- `install-agent` uses macOS launchd. On Linux, run `jev-imap-router watch` under systemd or tmux for now.
- Microsoft 365 work accounts that require OAuth for IMAP aren't supported yet (app passwords only).
- In Gmail, IMAP folders are labels: filing adds the `Sorted/...` label and removes the email from the Inbox.

## Credits

Inspired by [jevMail](https://github.com/ilyamk/jev-gmail-ai-spam-filter-and-labeling) by Ilia AGI,
which does this for Gmail via Google Apps Script. Presets and the classification policy are adapted
from it under the MIT license. Classification by [Jev](https://docs.typesafe.ai/introduction) from TypeSafe.

## License

MIT
