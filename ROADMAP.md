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
- [x] Post-deploy smoke test (`scripts/smoke_test.sh`, run by the deploy job): the table is ACTIVE; the site serves the app, its security headers, its files, a deep link and a `config.json` that matches the API; every API route answers 401 without a token. Read-only, never signs in or sends a push. The script itself is tested against a local stand-in (`tests/test_smoke.py`). Not covered: that the checker ran (the app's "Last checked" line shows that)

## Next

1. [x] Alert email: topic, crash alarm and the `ALERT_EMAIL` secret are in place and the subscription is confirmed (2026-10-30)
2. [x] Refresh-token rotation: every renewal issues a new refresh token (60 s grace for retries), so the session runs a year from the last renewal; a refresh whose response is lost, or an old token reused after 60 s, still needs a fresh sign-in
3. [ ] Phase 7: Black Friday polish (see App polish below); Black Friday 2026 is Nov 27

### Black Friday plan (Nov 27), in this order

1. [x] Quiet hours (see App polish)
2. [x] Digest: more than 3 alerts waiting for one user go out as one summary push (see App polish)
3. [x] ~~Alarm for the checker not running~~: not wanted (2026-10-31). The "Last checked" line (item 4) turns amber after 90 minutes, which covers it without an alarm
4. [x] "Last checked" line (Deals and Settings): each run saves one shared `CHECKER`/`STATUS` item (time, feeds read, failed, skipped); the app shows "Checked 12 min ago", adds "6 of 8 feeds" when some did not answer, and turns amber with "new deals may be delayed" after 90 minutes. Nothing is saved when the main feed is down or every feed fails, so the line goes stale instead of lying; the line refreshes every 5 minutes and when the app comes back to the front
5. [x] Better keyword syntax: `-word` exclusions and `"exact phrases"`, so a broad keyword like "TV" is less noisy (see App polish)
6. [x] Fetch feeds concurrently (see Engineering backlog)
7. [x] Post-deploy smoke test (see Done)

## Sources and feeds

| Source | Status | Notes |
|---|---|---|
| Dealnews main feed | **Live** | Public RSS, robots.txt allows it, 50 latest deals. Its RSS page (dealnews.com/rss/, read 2026-10-30) says "the feeds are yours to use": links and referral codes must stay unchanged, credit Dealnews if published publicly, and the feed content may not go in a public browser extension |
| Dealnews extra feeds | **Live** | Most Popular, Staff Pick (editors' choice), and the Electronics, Computers, Clothing & Accessories and Home & Garden categories: each adds deals the main feed has already scrolled past (a test on 2026-10-30 found 24-36 not in the main feed, per feed). Optional: one failing is logged, not an error. Eight requests per run, read three at a time with each request starting at least 0.5 s after the one before; reading stops starting new feeds after 40 s |
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

- [x] Quiet hours (Settings): a whole-hour window, read in the device's time zone (stored when notifications are turned on, and sent again each time the window is saved). Inside it deals are still saved, their alerts wait and go out when the window ends (as one summary push if there are more than 3); an alert held more than 24 hours is dropped. No time zone known means nothing is held
- [ ] Appearance: Light and Auto (colours are tokens in `frontend/src/styles.css`)
- [x] Rename a watch on the Detail screen (Name field above the price limit)
- [x] Edit a keyword's highest price in the Keywords screen. Choosing feeds per keyword is not offered: Dealnews is the only live feed, so there is nothing to choose yet
- [ ] Price-history chart on Detail (needs checker data)
- [x] Digest: when more than 3 alerts are waiting for one user (new deals, deals held by quiet hours, deals whose push failed earlier), they go out as one push, "12 new deals" with the busiest keywords ("TV (5), OLED (4), Dyson (2) and 1 more"), opening the Deals list; 3 or fewer still get one push each. This replaced the 5-per-run cap, so a flood is no longer spread over later runs. The summary leaves out keyword syntax (`-mount`, quotes) and counts keywords that differ only in case together. Not done: a daily digest, or a setting for the threshold
- [x] Keyword syntax: `TV -mount -"wall mount"` skips deals with those words (the store and category count too); `"Pro Max" case` needs each quoted phrase anywhere and the plain words as one phrase in order; a plain keyword works as before. A `-` only excludes before a letter (`-15`, `-5%` stay plain text) and a quote only opens a phrase at the start of a word (`55" OLED` stays plain text). Two keywords that mean the same (case, spacing, quote style, term order) count as duplicates. Curly quotes from the phone keyboard are accepted. New keywords that cannot be read (only exclusions, an unclosed quote) are refused. The Keywords screen shows a one-line hint. Not done: OR between words
- [x] Deals without a price: when the feed gives none, a price is read from the title, but only if it names exactly one dollar amount ("for $199", "drops to $199"). Discounts ("$20 off", "save $50"), gift cards, cash and rewards, shipping, spending thresholds ("orders over $50", "$35+") and monthly payments are set aside, and two real prices ("was $299, now $199", "from $299 to $199") give no price at all. The feed's own price always wins, also when it comes from a later feed. Not done: a per-keyword option to include deals that still have no price (store-wide Black Friday sales are mostly percentages, so a price limit still skips them)
- [ ] "Not interested" on a deal in the Deals list, which could suggest an exclusion for that keyword
- [x] "Last checked" line (Black Friday plan, item 4)
- [x] Watches whose store has no checker: the app says so instead of "Waiting for first check" forever. The pill reads "Prices not read yet", Watching, Add and Detail show one note ("Store prices aren't read yet ... use Keywords"), the "Checking this product" switch is hidden (unless the watch is already paused, so it can be resumed), and the notification text only mentions keyword deals. One flag, `STORE_PRICES_CHECKED` in `frontend/src/format.ts`, switches all of it back: flip it in the PR that ships the first store checker
- [ ] More users (items are keyed per user; checks would be shared per product link)

## Engineering backlog (from code reviews)

- [ ] Feed checker finds rules with a full-table Scan every 30 minutes: fine now, add a rule index if the table or user count grows
- [ ] `notify` re-queries a user's devices per deal (at most 3 per run now, or one summary): fetch once per user
- [ ] Share the "load / retry" notice and fetch pattern across screens (repeated in five places)
- [ ] Rendering tests for the screens (needs a DOM test setup and a new dev dependency; the logic is covered by pure-function tests)
- [x] Fetch feeds concurrently: three workers, requests start at least 0.5 s apart (an estimate: reading should drop from about 10-15 s to about 4-6 s; check the run log after deploy). Still polite: no bursts, the same 40 s budget, a failing extra feed is only logged
- A dead or renumbered extra Dealnews feed (a changed category id, say) is only logged, and no alarm will be added (2026-10-31). The "Last checked" line shows "6 of 8 feeds" when some do not answer
- [x] A broad keyword (like "TV") matching many deals on the first run after new feeds: solved by the digest (one summary push)
- ~~An alarm for the checker not running at all~~: decided against (2026-10-31); see "Decisions on record"
- ~~Extend the smoke test to prove the checker ran recently~~: dropped with the alarm (it needed extra deploy-role permissions); the app's "Last checked" line shows it instead
- [ ] Alerts left unsent (quiet hours, a failed push) are retried until their deal is 24 hours old
- [ ] Duplicate keyword check is read-then-write: two simultaneous adds can slip past (strict fix needs a different key design)
- [ ] Older keyword rules may still list Reddit or Slickdeals as sources (harmless, hidden in the UI); migrate if it ever matters
- [ ] Dependabot: `aws-cdk-lib` updates are paused until botocore allows python-dateutil 3 (remove the ignore in `.github/dependabot.yml` then; never merge an update that drops `cryptography` from `layer/requirements.txt`)
- [ ] After Black Friday: check whether the Black Friday feed still exists, and drop it if not
- [ ] CSP `connect-src` allows any `*.execute-api` host in the region; pinning needs a custom domain
- [ ] WAF and a stricter CloudFront TLS floor need a custom domain or budget (about $5/month for WAF)

## Decisions on record

- Password sign-in stays on next to passkeys: it is the backup if the phone is lost (2026-10-28)
- Slickdeals and Reddit are not read; the reasons are in the table above (2026-10-29)
- No CloudWatch alarms beyond the existing crash alarm: not for the checker not running, not for a dead extra feed (2026-10-31). The app's "Last checked" line is the signal instead
- Code review (`/code-review high`) runs on every code diff before it is committed, and its findings go in the PR (2026-10-29)
