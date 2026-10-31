#!/usr/bin/env bash
# Post-deploy smoke test: the live site and API answer the way they should. Reads only, never signs in, sends no push.
# Usage: SITE=https://... API=https://... [TABLE=name] scripts/smoke_test.sh   (TABLE adds a DynamoDB status check; needs the aws CLI)
set -uo pipefail

: "${SITE:?set SITE to the site URL}" "${API:?set API to the API URL}"
SITE="${SITE%/}"
API="${API%/}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
failed=0

fail() { echo "FAIL $*"; failed=1; }
pass() { echo "ok   $*"; }

# fetch URL [curl args...]: sets CODE (000 when nothing answered), HEADERS and BODY from the last attempt only.
# A fresh deploy can answer 5xx or 429 once, so those (and no answer) are tried again, up to 4 times.
fetch() {
  local url="$1" attempt; shift
  for attempt in 1 2 3 4; do
    CODE="$(curl -s --max-time 20 -D "$work/headers" -o "$work/body" -w '%{http_code}' "$@" "$url")" || CODE=000
    [ -f "$work/headers" ] || : >"$work/headers"
    [ -f "$work/body" ] || : >"$work/body"
    case "$CODE" in 000 | 429 | 5??) [ "$attempt" = 4 ] || sleep "${SMOKE_RETRY_PAUSE:-2}" ;; *) break ;; esac
  done
  HEADERS="$(cat "$work/headers")"
  BODY="$(cat "$work/body")"
  rm -f "$work/headers" "$work/body"
}
has_header() { grep -qi "^$1:" <<<"$HEADERS"; }
header_value() { grep -i "^$1:" <<<"$HEADERS" | head -n1 | cut -d: -f2- | tr -d '\r' | tr 'A-Z' 'a-z'; }

if [ -n "${TABLE:-}" ]; then
  state="$(aws dynamodb describe-table --table-name "$TABLE" --query 'Table.TableStatus' --output text 2>&1)"
  [ "$state" = ACTIVE ] && pass "table is ACTIVE" || fail "table status: $state"
fi

# ---- the site: the app, its security headers, its files, and the settings the deploy wrote
fetch "$SITE/"
[ "$CODE" = 200 ] && pass "GET / -> 200" || fail "GET / -> $CODE"
grep -q 'id="app"' <<<"$BODY" && pass "home page is the app" || fail "home page is not the app"
for header in content-security-policy strict-transport-security x-frame-options x-content-type-options referrer-policy; do
  has_header "$header" && pass "header $header" || fail "header $header is missing"
done

# CloudFront answers a missing file with the app's HTML page and status 200, so the type of each file is checked too.
for file in "/manifest.webmanifest:json" "/sw.js:javascript" "/icon-192.png:image/png"; do
  path="${file%%:*}"; kind="${file#*:}"
  fetch "$SITE$path" -r 0-0
  type="$(header_value content-type)"
  { [[ "$CODE" = 200 || "$CODE" = 206 ]] && [[ "$type" == *"$kind"* ]]; } && pass "GET $path -> $CODE ($type)" || fail "GET $path -> $CODE ($type), want $kind"
done

# Any unknown path falls back to the app (the app's own routes live after a # and never reach the server).
fetch "$SITE/no-such-page"
{ [ "$CODE" = 200 ] && grep -q 'id="app"' <<<"$BODY"; } && pass "an unknown path falls back to the app" || fail "an unknown path does not fall back to the app ($CODE)"

fetch "$SITE/config.json"
if jq -e --arg api "$API" '.apiUrl == $api and (.authUrl | startswith("https://")) and (.clientId | length > 0)' >/dev/null 2>&1 <<<"$BODY"; then
  pass "config.json points at this API and sign-in"
else
  fail "config.json is missing or does not match this API"
fi

# ---- the API: every route refuses a request without a token (tests/test_smoke.py keeps this list equal to infra/web.py)
routes=(
  "GET /me/watches" "POST /me/watches" "GET /me/watches/abc" "PUT /me/watches/abc" "DELETE /me/watches/abc"
  "GET /me/rules" "POST /me/rules" "PUT /me/rules/abc" "DELETE /me/rules/abc"
  "GET /me/deals" "GET /me/settings" "PUT /me/settings" "GET /me/status"
  "POST /me/push/status" "PUT /me/push" "DELETE /me/push" "POST /me/push/test"
)
for route in "${routes[@]}"; do
  fetch "$API${route#* }" -X "${route%% *}"
  [ "$CODE" = 401 ] && pass "$route -> 401" || fail "$route -> $CODE (want 401)"
done

fetch "$API/me/watches" -H "Authorization: Bearer not-a-real-token"
[ "$CODE" = 401 ] && pass "GET /me/watches with a bad token -> 401" || fail "GET /me/watches with a bad token -> $CODE (want 401)"

[ "$failed" = 0 ] && echo "Smoke test passed" || { echo "Smoke test FAILED"; exit 1; }
