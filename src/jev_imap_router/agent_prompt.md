You're helping me set up jev-imap-router, a tool that sorts my email over IMAP using Jev (TypeSafe's
classifier model). Your job: design email categories that fit MY actual mail, test them in preview
mode, and refine them until they work well. Jev does the classifying; you write the category rules.

Ground rules:
- Never switch `mode` to `live`, and never run `backfill` or `watch` without --dry-run, unless I
  explicitly say so. Preview only. Nothing gets moved or deleted while you work.
- My mail stays on this machine. Don't paste email contents anywhere outside this session.
- Config: ~/.jev-imap-router/config.yaml (or $JEV_IMAP_ROUTER_HOME). Run commands with `jev-imap-router`.
  If it isn't on PATH, use `uvx jev-imap-router`.

Steps:

1. Understand my mail.
   Run `jev-imap-router discover --days 60`, then read ~/.jev-imap-router/logs/discover.md: a table of
   who emails me, how much of it is bulk, and what I reply to. Only open logs/sample.jsonl if you
   need specifics. Tell me in a few sentences what my mail is mostly about.

2. Propose categories. Ask me to confirm before writing them.
   - Inbox categories (`action: keep`) for mail I need to see: real people, customers, things needing
     action. Flag the "needs action" one (`flag: true`). Always keep a fallback like "Review".
   - Filing categories (`action: move`) for high-volume automated mail: receipts, newsletters,
     notifications, promotions, calendar, travel, cold outreach, and anything big and specific to me
     (e.g. my own product's automated emails, lead alerts, a hobby).
   - Keep "Junk" with `folder: "@junk"` and `min_confidence: 0.90`.
   - 8 to 16 categories total. Jev accepts up to 255 options, but clear beats many.
   - Write each `when` as literal inclusions and exclusions, naming real senders and examples from my
     mail ("Stripe, GitHub, and AWS receipts"; "Excludes marketing from companies I already use").
     Jev reads instructions literally, so say exactly what you mean.

3. Test in preview.
   Run `jev-imap-router preview --limit 300`, then `jev-imap-router review` and read the output.
   It shows where mail would go, each folder's top senders, moves worth a second look, and
   low-confidence decisions.

4. Fix what's wrong, and repeat step 3 two or three times:
   - A sender in the wrong folder: tighten the `when` text of both categories involved (add the sender
     as an example or an exclusion). Don't add special cases in code.
   - Real people or conversations being filed: they should stay in the Inbox. Conversations I've
     replied to are protected automatically; strengthen the Inbox category wording for the rest.
   - Lots of mail stuck in the Inbox with low confidence between two folders: the descriptions
     overlap, so make them distinct.
   - Anything important going to Spam: stop and tell me.

5. Report back: the final categories, what the last preview would do (counts per folder), anything
   still uncertain, and the cost so far (`jev-imap-router stats --include-preview`). Then tell me the
   next steps: set `mode: live`, run `jev-imap-router backfill`, then `jev-imap-router install-agent`.
