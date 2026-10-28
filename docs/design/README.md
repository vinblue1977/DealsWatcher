# Design

Approved dark-mode iPhone mockups (390×844). Source files are Design Component pages (`*.dc.html`) with the canvas layout in `canvas.json`; they use made-up sample products and prices.

| File | Screen |
|---|---|
| `Main.dc.html` | Watching list |
| `Detail.dc.html` | Watch detail with price chart |
| `Add.dc.html` | Add watch |
| `Deals.dc.html` | Deals feed |
| `Keywords.dc.html` | Keyword alerts |
| `Settings.dc.html` | Settings (notifications, quiet hours, appearance, store status) |
| `Lock.dc.html` | Push notifications on the lock screen |

Colours are semantic tokens (`--bg`, `--surface`, `--text`, `--muted`, `--accent`, `--good`, `--warn`, `--bad`); the app's real values live in `frontend/src/styles.css`. Light mode will be a second value set, with no component changes.
