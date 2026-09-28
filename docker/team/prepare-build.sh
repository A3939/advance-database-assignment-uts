#!/bin/sh
# Export Git commit/tree objects without requiring Python on the host.
set -eu
umask 077

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"
proof_dir=artifacts/team
proof_path=$proof_dir/build-provenance.objects
mkdir -p "$proof_dir"
# Remove stale proof even when the checkout or HEAD check below fails.
rm -f "$proof_path"

fail() {
    printf '%s\n' "Build preparation failed: $*" >&2
    exit 1
}

[ "$(git rev-parse --show-object-format)" = sha1 ] ||
    fail 'This build requires a SHA-1 Git repository.'
head=$(git --no-replace-objects rev-parse --verify 'HEAD^{commit}')
case "$head" in
    *[!0-9a-f]*|'') fail 'HEAD must be a full 40-character Git commit SHA.' ;;
esac
[ "${#head}" -eq 40 ] || fail 'HEAD must be a full 40-character Git commit SHA.'

check_clean() {
    git diff --quiet "$head" -- ||
        fail 'Commit or restore tracked changes, then prepare again. No build proof was kept.'
}
check_clean

temp_dir=$(mktemp -d "$proof_dir/.prepare-build.XXXXXX")
trap 'rm -rf "$temp_dir"' 0
trap 'exit 1' HUP INT TERM

root_tree=$(git --no-replace-objects rev-parse "$head^{tree}")
git --no-replace-objects ls-tree -r -t --format='%(objecttype) %(objectname)' "$head" > "$temp_dir/tree-rows"
while read -r object_type object_id; do
    if [ "$object_type" = tree ]; then
        printf '%s\n' "$object_id"
    fi
done < "$temp_dir/tree-rows" > "$temp_dir/tree-ids"
LC_ALL=C sort -u "$temp_dir/tree-ids" > "$temp_dir/unique-tree-ids"
{
    printf '%s\n' "$head" "$root_tree"
    cat "$temp_dir/unique-tree-ids"
} > "$temp_dir/object-ids"

# Direct redirection preserves raw tree NUL bytes and UTF-8 commit messages.
git --no-replace-objects cat-file --batch < "$temp_dir/object-ids" > "$temp_dir/proof"
[ "$(git --no-replace-objects rev-parse --verify HEAD)" = "$head" ] ||
    fail 'HEAD changed during preparation. Run this script again.'
check_clean
mv -f "$temp_dir/proof" "$proof_path"

printf 'Prepared build proof for Git commit %s.\n' "$head"
printf 'Set ARSIA_REVISION in .env to %s.\n' "$head"
printf '%s\n' 'Next: docker compose --profile tools build app'
