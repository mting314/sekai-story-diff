#!/usr/bin/env bash
# Bring the generated media back down. Only needed to *render* locally: the site
# itself reads it from the bucket, so browsing and developing need nothing here.
#
# The renderer skips any sprite already on disk, so without this a local run would
# redraw all ~2,400 poses from scratch instead of just the new ones.
set -euo pipefail
cd "$(dirname "$0")/.."
gcloud storage rsync gs://sekai-story-diff-assets web/public --recursive
echo "pulled $(find web/public -type f \( -name '*.webp' -o -name '*.png' \) | wc -l | tr -d ' ') files"
