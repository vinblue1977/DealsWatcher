# People and accounts

DealsWatcher is invite-only: there is no sign-up page. Only accounts the owner creates can sign in. It is meant for a few people the owner knows.

## What each person gets

Everything is separate per person: their own watches, keywords, deals, notification devices and settings. The server takes the person's id from their verified login token and never from the request, so nobody can read or change anyone else's data (`tests/test_api.py` tries every route as a second user to prove it).

Shared on purpose: the feed checker downloads each Dealnews feed once per run and then matches it against everyone's keywords. Each person is alerted only about their own keywords.

Limits per person: 100 watches, 50 keywords, 10 notification devices.

## Add someone

```
scripts/invite_user.sh friend@example.com
```

Needs AWS access (`aws login`). They get an email that tells them to open the site on their iPhone in Safari, sign in with the temporary password (valid 3 days), add the app to the Home Screen, then add a passkey and turn on notifications in Settings. Each person signs in on their own phone; their session lasts up to a year.

If the temporary password expires before they use it, send a fresh one:

```
scripts/invite_user.sh friend@example.com --resend
```

## Remove someone

```
scripts/remove_user.py friend@example.com            # preview: shows what would be removed, changes nothing
scripts/remove_user.py friend@example.com --yes      # remove the account and all of their data (cannot be undone)
scripts/remove_user.py friend@example.com --disable  # block sign-in, turn their keyword alerts off, keep the data
```

What happens, in order: sign-in is blocked and their refresh tokens are revoked, their items are deleted from the table (watches, keywords, deals, devices), then the account is deleted. Only that person's items are touched.

**One limit to know about:** access tokens that were already issued stay valid for up to 1 hour and cannot be recalled. Someone who is signed in at that moment can still change their own data for up to an hour, and anything they create is left behind under their user id. The script prints that id. An hour later run `scripts/remove_user.py <user id> --yes` to clear it.

`--disable` stops them signing in and turns their keywords off (otherwise the feed checker would keep alerting their phone), but keeps their data. To bring someone back, enable them in the sign-in service and turn their keywords back on in the app.

## Privacy notes

- The table stores no email addresses; items are keyed by an internal id. The email lives only in the sign-in service.
- Push subscription addresses are secrets (anyone holding one can push to that device). They only travel in request bodies, never in URLs, and are deleted with the person.
- Never put emails, passwords or keys in the repository, commits or pull requests.
