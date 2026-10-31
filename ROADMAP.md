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
- [x] Post-deploy smoke test (`scripts/smoke_test.sh`, run by the deploy job): the table is ACTIVE; the site serves the app, its security headers, its files, a deep link and a `config.json` that matches the API; every API route answers 401 without a token. Read-only, never signs in or sends a push. The script itself is tested against a local stand-in (`tests/test_smoke.py`). Not covered: that the checker ran (needs extra deploy-role permissions; see the alarm item below)

## Next

1. [x] Alert email: topic, crash alarm and the `ALERT_EMAIL` secret are in place and the subscription is confirmed (2026-10-30)
2. [x] Refresh-token rotation: every renewal issues a new refresh token (60 s grace for retries), so the session runs a year from the last renewal; a refresh whose response is lost, or an old token reused after 60 s, still needs a fresh sign-in
3. [ ] Phase 7: Black Friday polish (see App polish below); Black Friday 2026 is Nov 27

### Black Friday plan (Nov 27), in this order

1. [x] Quiet hours (see App polish)
2. [ ] Digest instead of one push per deal, or a higher per-run cap: broad keywords will flood the 5-per-run cap (see App polish)
3. [ ] Alarm for the checker not running at all, and a metric or alarm for a dead extra feed (see Engineering backlog)
4. [ ] "Last checked" line in Settings or Deals ("Checked 12 min ago, 8 feeds OK"): the run summary logged since #32 already has the data; store it on a small item the app can read
5. [ ] Better keyword syntax (in progress): `-word` exclusions and `"exact phrases"`, so a broad keyword like "TV" is less noisy
6. [ ] Fetch feeds concurrently (in progress; see Engineering backlog)
7. [x] Post-deploy smoke test (see Done)

## Sources and feeds

| Source | Status | Notes |
|---|---|---|
| Dealnews main feed | **Live** | Public RSS, robots.txt allows it, 50 latest deals. Its RSS page (dealnews.com/rss/, read 2026-10-30) says "the feeds are yours to use": links and referral codes must stay unchanged, credit Dealnews if published publicly, and the feed content may not go in a public browser extension |
| Dealnews extra feeds | **Live** | Most Popular, Staff Pick (editors' choice), and the Electronics, Computers, Clothing & Accessories and Home & Garden categories: each adds deals the main feed has already scrolled past (a test on 2026-10-30 found 24-36 not in the main feed, per feed). Optional: one failing is logged, not an error. Eight requests per run, 1 s apart; reading stops starting new feeds after 40 s |
| Dealnews Black Friday feed | **Live** | Store-wide sales, mostly without a price; a price limit on a keyword skips them. Seasonal: if it disappears after the season it is logged, not an error |
| blackfriday.com | Idea, on hold | robots.txt allows its sitemap (327 store ad pages under `/ads/`), but it has no feed and its terms of use have **not been read yet**. Idea: detect new `/ads/` pages by comparing sitemap copies (a store posted its ad), sitemap dates are unreliable, so diff the URL list. No prices |
| Reddit | Skipped for now (2026-10-30) | robots.txt disallows everything. Two permitted routes, both need Reddit's approval: the official API with your own app credentials (access must be requested and approved first), or a small Devvit app installed in your own subreddit that searches the deal subreddits (`reddit.searchPosts` with `subredditName`, no key) and sends results to a new ingest route (HTTP fetch needs Reddit to approve our API hostname). Not worth it before Black Friday: a second codebase, a new public route to secure, untested cross-subreddit reads, Reddit's developer terms unread. Revisit after Black Friday if you still miss deals |
| Slickdeals | Not used | robots.txt disallows its RSS for programs. Use Slickdeals' own Deal Alerts in their app (your account). Or ask them for permission |
| CNET, theblackfriday.com | Not used | Ziff Davis terms prohibit crawling, scraping and aggregating without written permission |
| Newegg | Not used | Cloudflare bot protection, no feed. Workaround for deals: the keyword "Newegg" matches Dealnews deals sold by Newegg |
| PageCrawl.io (third-party page monitor) | Skipped by choice | Free plan: 6 pages, hourly checks. Could cover Newegg pages outside this app |
| Brad's Deals | Not used | Terms forbid bots, spiders and scrapers |
| Ben's Bargains | Not used | robots.txt allows crawling, but the Internet Brands terms ban spiders, scrapers and RSS feeds |
| Dealsea | Not used | No feed, no terms page found |
| Woot | Not used | Terms ban scraping. An official API exists (`developer.woot.com`, 1,000 requests a day, key requested through their forums); Woot deals only |
| Hip2Save | Not used | robots.txt allows its feed, but its terms of use ban robots, spiders and "any manual process to monitor or copy" |
| 9to5Toys | On hold | Valid public RSS feed that robots.txt allows (Best Buy and Amazon deals with prices), but no terms page could be found. Do not build on it until its terms are read |
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

- [x] Quiet hours (Settings): a whole-hour window, read in the device's time zone (stored when notifications are turned on, and sent again each time the window is saved). Inside it deals are still saved, their alerts wait and go out when the window ends (newest first, 5 per run); an alert held more than 24 hours is dropped. No time zone known means nothing is held
- [ ] Appearance: Light and Auto (colours are tokens in `frontend/src/styles.css`)
- [x] Rename a watch on the Detail screen (Name field above the price limit)
- [x] Edit a keyword's highest price in the Keywords screen. Choosing feeds per keyword is not offered: Dealnews is the only live feed, so there is nothing to choose yet
- [ ] Price-history chart on Detail (needs checker data)
- [ ] Optional digest instead of one push per deal (Black Friday plan, item 2)
- [ ] Keyword syntax: `-word` and `-"two words"` exclude a deal, `"exact phrase"` terms must each appear; plain keywords keep working as they do now. The Add/Edit keyword screen shows a one-line hint
- [ ] Deals without a price: a keyword with a price limit skips them today. Option per keyword to include them marked "no price", or to read a price from the title ("$199") when the feed has none
- [ ] "Not interested" on a deal in the Deals list, which could suggest an exclusion for that keyword
- [ ] "Last checked" line (Black Friday plan, item 4)
- [ ] Watches whose store has no checker show "Waiting for first check" forever: hide or relabel them ("Not checked yet, store prices are not read") until a store checker exists, so the app does not look broken to invited people
- [ ] More users (items are keyed per user; checks would be shared per product link)

## Engineering backlog (from code reviews)

- [ ] Feed checker finds rules with a full-table Scan every 30 minutes: fine now, add a rule index if the table or user count grows
- [ ] `notify` re-queries a user's devices per deal (at most 5 per run): fetch once per user
- [ ] Share the "load / retry" notice and fetch pattern across screens (repeated in five places)
- [ ] Rendering tests for the screens (needs a DOM test setup and a new dev dependency; the logic is covered by pure-function tests)
- [ ] Fetch feeds concurrently (today one after another with a 1 s pause; in progress). Keep it polite: a small worker limit, not all eight at once
- [ ] A dead or renumbered extra Dealnews feed (a changed category id, say) is only logged, so nothing alerts you; add a metric or alarm if coverage matters (an alarm costs ~$0.10/month past the free 10)
- [ ] A broad keyword (like "TV") on the first run after new feeds can match many deals, but only 5 pushes go out per user per run and deals older than 6 hours are dropped; raise the cap or add a digest if that bites
- [ ] An alarm for the checker not running at all (no invocations for hours): a second alarm, ~$0.10/month once past the free 10. Do this one before Black Friday
- [ ] Extend the smoke test to prove the checker ran recently (the deploy role needs permission to read the checker's logs or metrics; best done with the alarm above)
- [ ] Alerts left unsent (quiet hours, the 5-per-run cap, a failed push) are retried until their deal is 24 hours old
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
