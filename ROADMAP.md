# Roadmap

Cost target ≈ $0.10–0.50/month (AWS Budget alert as a cap).

How to read this: `[x]` done, `[ ]` open. Items marked **needs you** wait on something only you can supply. Check an item off in the PR that does it.

## Done

- [x] Phase 0: dark-mode iPhone mockups approved (`docs/design`)
- [x] Phase 1: repo + CI skeleton (same checks as TennisTracker)
- [x] Phase 2: AWS foundation (table, GitHub OIDC deploy role), CI deploy jobs, VAPID key in SSM. Account-wide cost budgets ($5, alerts at 80% and 100%) already exist
- [x] Phase 3: hosting (private S3 behind CloudFront), passkey sign-in (session renewed on every refresh, up to a year idle), API, app sign-in
- [x] Phase 4: PWA screens (Watching, Add, Detail, Deals, Keywords, Settings), service worker, push notifications, install hint, app icon
- [x] Phase 6: feed checker for Dealnews: the main feed (`dealnews.com/?rss=1`) and the Black Friday feed (`dealnews.com/f1676/Black-Friday/?rss=1`), every 30 minutes, keyword alerts with one push per deal
- [x] Security hardening pass (least-privilege table access, request size cap, push endpoint kept out of URLs)
- [x] Alert topic + crash alarm on the feed checker: emails when it fails on two runs in a row (about an hour); no recovery email, and no email if it stops running at all (see Engineering backlog); the address comes from a deploy secret
- [x] Multi-user: invite-only accounts (no sign-up page), invitation email with setup steps, `scripts/invite_user.sh` and `scripts/remove_user.py` (removes the account and all of their data), per-user isolation tested on every route. See `docs/users.md`

## Next

1. [x] Alert email: topic, crash alarm and the `ALERT_EMAIL` secret are in place and the subscription is confirmed (2026-10-30)
2. [x] Refresh-token rotation: every renewal issues a new refresh token (60 s grace for retries), so the session runs a year from the last renewal; a refresh whose response is lost, or an old token reused after 60 s, still needs a fresh sign-in
3. [ ] Phase 7: Black Friday polish (see App polish below); Black Friday 2026 is Nov 27

## Sources and feeds

| Source | Status | Notes |
|---|---|---|
| Dealnews main feed | **Live** | Public RSS, robots.txt allows it, 50 latest deals |
| Dealnews Black Friday feed | **Live** | Store-wide sales, mostly without a price; a price limit on a keyword skips them. Seasonal: if it disappears after the season it is logged, not an error |
| blackfriday.com | Idea, on hold | robots.txt allows its sitemap (327 store ad pages under `/ads/`), but it has no feed and its terms of use have **not been read yet**. Idea: detect new `/ads/` pages by comparing sitemap copies (a store posted its ad), sitemap dates are unreliable, so diff the URL list. No prices |
| Reddit | Not used | robots.txt disallows everything. Permitted route: the official API with your own Reddit app credentials (needs approval). **Needs you** if wanted |
| Slickdeals | Not used | robots.txt disallows its RSS for programs. Use Slickdeals' own Deal Alerts in their app (your account). Or ask them for permission |
| CNET, theblackfriday.com | Not used | Ziff Davis terms prohibit crawling, scraping and aggregating without written permission |
| Newegg | Not used | Cloudflare bot protection, no feed. Workaround for deals: the keyword "Newegg" matches Dealnews deals sold by Newegg |
| PageCrawl.io (third-party page monitor) | Skipped by choice | Free plan: 6 pages, hourly checks. Could cover Newegg pages outside this app |
| Amazon | Not planned | Blocks scrapers |

Rule for any new source: read its robots.txt **and** its terms of use first, identify the checker honestly, and skip it if it says no. No evasion (no disguised browsers, no rotating addresses).

## Store price checking (parked)

The watch list can hold product links, but nothing reads their prices yet, so watches show "Waiting for first check". Decision (2026-10-28): feeds first, no store scraping.

- [ ] **Tennis Warehouse** (the most plausible store): robots.txt allows product pages, no explicit ban found in its terms (keyword scan, not a legal review), price is plain page markup (`itemprop="price"`). Signals against: its robots.txt blocks a named price-monitor bot ("ChangeDetection"). If built: only its product pages, one request per product once or twice a day, 30 seconds between requests, honest User-Agent, stop at the first block ("Can't read price"). Alternative: ask them for permission first. Interim: keyword "Tennis Warehouse" (added). **Decision needed**
- [ ] **Best Buy** (official API, free key): the signup rejects free email providers and `.edu`. **Needs you**: a work or custom-domain email, or skip. Best Buy blocks page requests, so no API means no Best Buy. Never put the key in the chat or the repo (SSM only)
- [ ] Target, Walmart, Costco: not started. Terms restrict automated access; Target's price comes from an unofficial private API. Not planned
- [ ] Before any store checker: test from AWS, since cloud addresses are often blocked
- [ ] When a checker exists: price history storage, the price chart on the Detail screen, "At target" and drop alerts, store status in Settings, one crash alarm per checker

## App polish

- [ ] Quiet hours (Settings mockup; the app already stores the device time zone, the checker does not use it yet)
- [ ] Appearance: Light and Auto (colours are tokens in `frontend/src/styles.css`)
- [ ] Rename a watch on the Detail screen (the API supports it; old guessed names stay until renamed or re-added)
- [ ] Edit a keyword's highest price and feeds in the Keywords screen
- [ ] Price-history chart on Detail (needs checker data)
- [ ] Optional digest instead of one push per deal
- [ ] More users (items are keyed per user; checks would be shared per product link)

## Engineering backlog (from code reviews)

- [ ] Feed checker finds rules with a full-table Scan every 30 minutes: fine now, add a rule index if the table or user count grows
- [ ] `notify` re-queries a user's devices per deal (at most 5 per run): fetch once per user
- [ ] Share the "load / retry" notice and fetch pattern across screens (repeated in five places)
- [ ] Rendering tests for the screens (needs a DOM test setup and a new dev dependency; the logic is covered by pure-function tests)
- [ ] Fetch feeds concurrently if more are added
- [ ] An alarm for the checker not running at all (no invocations for hours): a second alarm, ~$0.10/month once past the free 10
- [ ] Alerts left unsent are only retried while their deal is still in a feed and under 6 hours old
- [ ] Duplicate keyword check is read-then-write: two simultaneous adds can slip past (strict fix needs a different key design)
- [ ] Older keyword rules may still list Reddit or Slickdeals as sources (harmless, hidden in the UI); migrate if it ever matters
- [ ] Dependabot: `aws-cdk-lib` updates are paused until botocore allows python-dateutil 3 (remove the ignore in `.github/dependabot.yml` then; never merge an update that drops `cryptography` from `layer/requirements.txt`)
- [ ] After Black Friday: check whether the Black Friday feed still exists, and drop it if not
- [ ] CSP `connect-src` allows any `*.execute-api` host in the region; pinning needs a custom domain
- [ ] WAF and a stricter CloudFront TLS floor need a custom domain or budget (about $5/month for WAF)

## Decisions on record

- Password sign-in stays on next to passkeys: it is the backup if the phone is lost (2026-10-28)
- Slickdeals and Reddit are not read; the reasons are in the table above (2026-10-29)
- Code review (`/code-review high`) runs on every code diff before it is committed, and its findings go in the PR (2026-10-29)
