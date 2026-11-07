#!/usr/bin/env bash
# Fails when the built index.html points at a local file that is not in the build (a file left out of the commit,
# say): the site answers a missing file with the app page, so nothing else would notice.
set -euo pipefail
dist="${1:?usage: check_dist.sh frontend/dist}"
missing=0
for ref in $(grep -oE '(src|href)="/[^"#?]+' "$dist/index.html" | sed -E 's/^(src|href)="//'); do
  if [ ! -f "$dist$ref" ]; then
    echo "index.html refers to $ref but $dist$ref does not exist"
    missing=1
  fi
done
exit "$missing"
