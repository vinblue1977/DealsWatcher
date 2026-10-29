# Roadmap

Cost target ≈ $0.10–0.50/month (AWS Budget alert as a cap).

## Done

- [x] Phase 0: dark-mode iPhone mockups approved (`docs/design`)
- [x] Phase 1: repo + CI skeleton (same checks as TennisTracker)

## Next

- [ ] Phase 2: AWS foundation (table, GitHub OIDC deploy role) and CI deploy jobs; VAPID key created in SSM by hand. Cost budgets already exist account-wide ($5, alerts at 80% and 100%); the alert email topic arrives with the first Lambda
- [ ] Phase 3: hosting, passkey sign-in (365-day session), API, app sign-in code. No alarms or alert email yet
- [ ] Phase 4: PWA shell + push
- [ ] Phase 5: alert email topic + one crash alarm per checker (each alarm past the account's free 10 costs ~$0.10/month); price checker (Best Buy first; then best-effort Target, Walmart, Tennis Warehouse, Costco). Before starting, test real product pages for Tennis Warehouse and Costco, ideally from AWS
- [x] Phase 6: feed checker for Dealnews (`dealnews.com/?rss=1` and its Black Friday feed `dealnews.com/f1676/Black-Friday/?rss=1`, every 30 minutes). Slickdeals and Reddit are not read: both disallow automated access in robots.txt (Reddit's official API needs your own credentials)
- [ ] Phase 7: Black Friday polish

## Later

- [ ] Light mode and Auto (colours are tokens in `frontend/src/styles.css`)
- [ ] More users (items are keyed per user; checks are shared per product URL)

## Sources

| Source | Kind | Expected reliability |
|---|---|---|
| Best Buy | Price (official API, free key) | High |
| Dealnews | Deal feed (public RSS, robots.txt allows it) | High |
| Slickdeals, Reddit | Deal feeds | Not used: robots.txt disallows automated access. Reddit's official API (OAuth app, your own credentials) is the permitted route if wanted later |
| Target, Walmart, Tennis Warehouse, Costco | Price (page parsing) | Not started: these sites' terms restrict automated access, and Target's price comes from an unofficial API. Decision (2026-10-28): feeds first, no store scraping |
| Newegg | Deals via feeds only | Blocked by Cloudflare when probed; direct price tracking is a stretch goal |
| Amazon | Not planned for v1 | Blocks scrapers |
