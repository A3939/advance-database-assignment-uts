#!/bin/sh
# Rebuild the committed checkout and replace only the dashboard container.
set -eu

fail() {
    printf 'Dashboard rebuild failed: %s\n' "$*" >&2
    exit 1
}

[ "$#" -eq 0 ] || fail 'Usage: sh docker/team/rebuild-dashboard.sh'
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir/../.."

command -v git >/dev/null 2>&1 || fail 'Git is required.'
command -v docker >/dev/null 2>&1 || fail 'Docker is required.'
[ -f .env ] || fail 'Create .env using the setup in docs/team-docker.md first.'

# Override stale terminal/.env revisions for every command in this run.
ARSIA_REVISION=$(git --no-replace-objects rev-parse --verify 'HEAD^{commit}')
export ARSIA_REVISION
[ -z "$(git status --porcelain --untracked-files=normal)" ] ||
    fail 'Commit your changes (including new files) first, then rerun. Use git status --short to inspect them.'

printf '%s\n' '[1/5] Checking Docker and Compose configuration...'
docker info >/dev/null
docker compose config --quiet

printf '%s\n' '[2/5] Preparing Git build proof...'
sh docker/team/prepare-build.sh
[ "$(git --no-replace-objects rev-parse --verify HEAD)" = "$ARSIA_REVISION" ] ||
    fail 'HEAD changed during preparation. Run this script again.'

printf '%s\n' '[3/5] Building the app image...'
docker compose --profile tools build app

printf '%s\n' '[4/5] Checking the image installation...'
docker compose --profile tools run --rm --no-deps app info

printf '%s\n' '[5/5] Recreating the dashboard...'
docker compose --profile web up -d --no-deps --force-recreate dashboard
docker compose --profile web ps dashboard
printf 'Dashboard recreated from %s. Refresh your browser.\n' "$ARSIA_REVISION"
