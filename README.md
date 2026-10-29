# DealsWatcher

An iPhone-first deal watcher (PWA) on serverless AWS: watch product prices against a target, match deal-feed keywords (Dealnews), and get push notifications on your Home Screen app.

Status: live for a few invited people. Watching, keyword deals from Dealnews, push alerts and passkey sign-in work; store price checking is parked (see [ROADMAP.md](ROADMAP.md)). Adding and removing people: [docs/users.md](docs/users.md).

Designs (dark mode first, light mode later): [docs/design](docs/design/README.md).

## Development

```sh
make install   # Python (uv if installed) + Node tools
make check     # everything CI runs: privacy, lint, tests, frontend, audit, synth
```
