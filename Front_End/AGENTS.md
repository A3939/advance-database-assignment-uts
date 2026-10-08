<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Local development workspace

- Use `Workspace/ARSIA` on `peixian/arsia-platform` as the canonical frontend workspace. The dashboard-trust changes are integrated here.
- The single local ARSIA preview uses `http://127.0.0.1:3100`. Run `npm run dev` for hot reload; `npm run start` uses the same port after a production build.
- Reuse a running ARSIA server. Do not start additional preview ports or create a worktree for routine edits. If a restart is needed, identify and stop only this project's existing server, then restart on 3100.
- If 3100 belongs to an unrelated process, report the conflict rather than killing it or silently selecting another port.

## Accepted local baseline and mirror (2026-10-08)

- The user accepted the currently integrated ARSIA as the normal local version. Read `docs/CURRENT-BASELINE.md` first; do not substitute historical candidates, Git HEAD, old demo snapshots, or old patches.
- `Workspace/ARSIA` is the source of truth and sole normal runtime on port 3100. `Workspace_Github/Front_End` is a source mirror, not an independently evolving demo or normal runtime. Make routine changes in ARSIA and synchronize the reviewed result forward; never reverse-sync an older mirror over ARSIA.
- Historical goals, failure records and archived candidate instructions are reference material, not automatic authorization to resume their jobs or change the active baseline during unrelated work.
- Keep private configuration, original data, databases, Studio content, runtime credentials and old evidence outside source synchronization. Do not delete historical material to hide versions; archive obsolete runnable outputs and retain rollback evidence.
- Before synchronization, check ownership/concurrent edits, back up overwritten target files, compare file hashes after copying, and verify the target build without starting a second service or replacing the normal data release.
