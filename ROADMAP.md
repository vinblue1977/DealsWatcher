# Roadmap

Cost target ≈ $0.10–0.50/month (AWS Budget alert as a cap).

## Done

- [x] Phase 0: dark-mode iPhone mockups approved (`docs/design`)
- [x] Phase 1: repo + CI skeleton (same checks as TennisTracker)

## Next

- [ ] Phase 2: AWS foundation (table, GitHub OIDC deploy role) and CI deploy jobs; VAPID key created in SSM by hand. Cost budgets already exist account-wide ($5, alerts at 80% and 100%); the alert email topic arrives with the first Lambda
- [ ] Phase 3: hosting, passkey sign-in, API
- [ ] Phase 4: PWA shell + push
- [ ] Phase 5: price checker (Best Buy first; then best-effort Target, Walmart, Tennis Warehouse, Costco). Before starting, test real product pages for Tennis Warehouse and Costco, ideally from AWS
- [ ] Phase 6: feed checker (Slickdeals, Dealnews `dealnews.com/?rss=1`, Reddit r/deals and r/buildapcsales)
- [ ] Phase 7: Black Friday polish

## Later

- [ ] Light mode and Auto (colours are tokens in `frontend/src/styles.css`)
- [ ] More users (items are keyed per user; checks are shared per product URL)

## Sources

| Source | Kind | Expected reliability |
|---|---|---|
| Best Buy | Price (official API, free key) | High |
| Slickdeals, Dealnews, Reddit | Deal feeds (RSS/JSON) | High |
| Target, Walmart, Tennis Warehouse, Costco | Price (page parsing) | Best-effort; shown as "Can't check" when blocked |
| Newegg | Deals via feeds only | Blocked by Cloudflare when probed; direct price tracking is a stretch goal |
| Amazon | Not planned for v1 | Blocks scrapers |
