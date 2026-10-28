# DealsWatcher

An iPhone-first deal watcher (PWA) on serverless AWS: watch product prices against a target, match deal-feed keywords (Slickdeals, Reddit), and get push notifications on your Home Screen app.

Status: skeleton. CI is in place; AWS resources and screens come next (see [ROADMAP.md](ROADMAP.md)).

Designs (dark mode first, light mode later): [docs/design](docs/design/README.md).

## Development

```sh
make install   # Python (uv if installed) + Node tools
make check     # everything CI runs: privacy, lint, tests, frontend, audit, synth
```
