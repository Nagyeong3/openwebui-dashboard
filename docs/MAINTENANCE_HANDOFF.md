# Maintenance handoff

Last updated: 2026-10-20 (Asia/Seoul)

2026-10-22 new implementation: see `docs/OPENWEBUI_0123_API.md` and `backend_v2/README.md`. User approved an API-first redesign against OpenWebUI 0.12.3. The snapshot-based deployed system below is historical context, not the new v2 architecture. Collector/cache/zero-usage user analytics are newly implemented; closed-network integration and React wiring are still pending.

2026-10-22 environment update: backend v2 now documents Miniconda 26.7.1 / Python 3.12 and same-platform conda-pack deployment. See backend_v2/README.md. Windows packaging/installation remains unverified; do not describe the generated-on-Windows environment ZIP as already built.

2026-10-22 Windows test fix: user reported WinError 32 removing unrelated.sqlite3. Fixed two test-only raw sqlite3 connections with contextlib.closing; sqlite3 connection context management commits/rolls back but does not close. Added Pack-CurrentCondaEnvironment.ps1 to package an existing application environment without rebuilding. Linux tests pass; Windows confirmation pending.

## Why this file exists

The latest implementation is on a closed-network development server and cannot be copied directly to this public repository. The current `main` branch is an early Streamlit scaffold. This document is a sanitized map of the later system, based on the development-server README, inspected screenshots, and fixes reported during maintenance.

It is a guide for diagnosis and recovery, not a replacement for the deployed source. Function names and paths below should be checked on the development server before editing.

## Current system shape

The deployed project began as a Streamlit dashboard and is being migrated to a React + FastAPI UI. Its data flow is intentionally based on snapshots and local caches:

1. A safe OpenWebUI SQLite snapshot is created on the operating server.
2. The dashboard downloads or copies the snapshot to its analysis DB.
3. The dashboard enriches OpenWebUI DB users with organization data from CSV.
4. LiteLLM `/spend/logs/v2` records are synchronized into a local token cache DB.
5. Question-category results are stored in a separate category cache DB.
6. React/FastAPI or the legacy Streamlit UI reads the local analysis data and caches.

This design avoids querying the live OpenWebUI DB and LiteLLM continuously.

### Data authority

| Data | Authority | Purpose |
| --- | --- | --- |
| User population and OpenWebUI activity | OpenWebUI DB snapshot | Determines which users exist and supplies chats/messages/files/models |
| Division, team, position | Organization CSV | Enriches matching OpenWebUI users |
| Token usage and spend | LiteLLM spend logs cached locally | Token and cost analytics |
| Question categories | Category definition CSV + local classification cache | Classification and category reporting |

The organization CSV is not a user registry for usage screens. A person present only in CSV must not appear as a dashboard user or team leader. A user present in the OpenWebUI DB can be included with zero usage when the selected view intentionally includes inactive DB users.

## Deployed project areas observed

The development-server README and screenshots show these areas. Exact paths may differ across the transition branch.

- `src/db`, `src/pages`, `src/services`, `src/ui`, `src/utils`
- organization mapping, analytics loading, user usage, team metrics, reporting
- token service, token cache service, token dashboard service
- category classifier and category cache
- `backend/services` for FastAPI-facing services
- `frontend` for the React/Vite client
- `scripts` for snapshot, update, token sync, and static frontend serving
- `docs` for architecture, operation, migration, and offline installation notes

The README references a dependency lock file for offline Windows installation and separate React/FastAPI migration documents. Check the server copy for the authoritative filenames and commands.

## OpenWebUI snapshot lifecycle

The deployed README describes two snapshot sources:

- Docker/local mode: create a safe SQLite snapshot from the OpenWebUI container or volume, verify it, and restart the application even when the copy fails.
- File-share or HTTP mode: download/copy the latest prepared snapshot.

The analysis side should:

1. Compare snapshot metadata with the saved synchronization state.
2. Write to a temporary file.
3. run SQLite `PRAGMA quick_check`.
4. back up the previous analysis DB.
5. atomically replace the analysis DB only after validation succeeds.

Do not publish real server addresses, container names, volume names, credentials, or absolute paths. The deployed README contains environment variables for source and destination DB paths, snapshot state, ready-hour handling, and optional local snapshot creation; copy their exact current values only inside the closed network.

## Organization mapping behavior

Observed mapping logic:

- Required CSV columns: division, team, name, and position.
- Optional user-ID columns accept several header aliases.
- CSV decoding attempts UTF-8 with BOM, UTF-8, and CP949.
- Match by OpenWebUI user ID first when supplied.
- Otherwise match by normalized name only when the CSV name is unique.
- Do not guess duplicate-name matches.
- Missing or unmatched organization values become the configured `Other` value and carry a mapping status.
- The Python constant represented as `"\ud300"` is simply the Unicode escape for `팀`.

The analytics loader already called `enrich_users_with_org(users, csv_path)` in the inspected server code. Do not add the same enrichment again in `user_service.py` without proving the deployed data path is missing it.

The analytics cache key was observed to include the organization CSV path, modification timestamp, and file size. This should invalidate the cached analytics data after a real file change, but cache behavior must still be checked in the running process.

## User usage and team/leader behavior

The user-usage service loads analytics data, filters by date, aggregates questions by DB user, optionally includes inactive DB users, applies organization filters, then builds user/team/leader detail.

Important distinctions:

- Filter options may use the organization roster so newly added organization values are selectable.
- Detail rows must still be derived from OpenWebUI DB users after organization enrichment.
- Team counts may use the organization roster for staffing metrics only when the metric definition explicitly requires it.
- Leader views generally identify a leader from the enriched position value containing the leader label.
- CSV-only leaders must not be appended to usage results.

On 2026-10-20, team options were reported visible in both token usage and user status after filter-option changes. The exact final deployed diff was not available and must be inspected before further edits.

The following idea was discussed but deliberately not applied: appending leaders directly from the CSV so they appear with zero usage. It violates the OpenWebUI-DB user authority rule and must not be reintroduced.

### Diagnostic order for a missing DB leader

1. Confirm the person exists in the OpenWebUI DB snapshot loaded by the dashboard.
2. Confirm ID or unique-name mapping attached the expected team and position.
3. Inspect duplicate-name and unmatched-user diagnostics.
4. Confirm the current date/view path invokes inactive-user inclusion when required.
5. Compare the filter source with the detail-row source.
6. Inspect analytics/cache invalidation using the CSV and DB snapshot metadata.

## LiteLLM token synchronization

The dashboard does not query LiteLLM on every page load. It synchronizes `/spend/logs/v2` into a local SQLite token cache and reads the cache for analytics. Subsequent refreshes continue from the latest saved request time and upsert duplicate request IDs.

The deployment filters logs to the configured OpenWebUI key alias. Category classification can use a separate LiteLLM key so category calls remain distinguishable from OpenWebUI usage logs.

### Applied fixes reported on 2026-10-20

- Spend-log date parameters were changed from raw ISO formatting to the date-time form accepted by the deployed LiteLLM endpoint. The successful manual request used `YYYY-MM-DD HH:MM:SS` boundaries.
- Spend-log page size is capped at 100 before calling LiteLLM because the endpoint rejected larger values with HTTP 422.

Verify the exact deployed format and boundary construction before changing it again. The screenshot review did not establish whether end-of-day and multi-day pagination have complete gap-free coverage.

### HTTP status interpretation

`POST /api/tokens/sync` can return HTTP 200 from the dashboard API while its JSON body reports `ok: false` and an upstream LiteLLM HTTP 422. The outer API status only confirms that the wrapper handled the request. Always inspect the response body.

Opening `/api/tokens/sync` in the browser address bar sends GET, so `Method Not Allowed` is expected for a POST-only route.

The token fetcher uses `urllib` in the inspected code. Its response and `HTTPError` objects do not provide a requests-style `.text` attribute. Read and decode the body instead, for example:

```python
body = error.read().decode("utf-8", errors="replace")
```

Never log the authorization header, API key, or a URL containing a key query parameter.

## Category classification

The development-server README describes a category CSV with category, description, keywords, examples, and active fields. Classification calls LiteLLM chat completions directly and stores results in a local category cache. Existing classifications can be reused by message ID and question hash. Low-confidence or unclassifiable results are stored as `Other` according to the configured threshold.

Browser GET caching may retain analysis responses for a limited time. Update workflows should invalidate relevant frontend caches after DB, token, or category refreshes.

## Update behavior

The operations page provides ordered update workflows:

- Quick update: fetch the latest OpenWebUI snapshot, synchronize recent LiteLLM logs, then classify recent uncategorized questions.
- Full update: fetch the snapshot, synchronize logs, then repeatedly classify the full remaining category workload in bounded batches.

The last run state is persisted so React reloads can show the previous status. A DB snapshot failure should stop later stages. Token or category failures should preserve already valid data and record the failure for diagnosis.

## Known uncertainty and open checks

- The full closed-network source has not been copied to GitHub, so this repository cannot reproduce the deployed build yet.
- The final user-status filter-option patch needs a sanitized diff or direct server inspection before it can be documented as code.
- The missing/zero-usage leader case needs validation against the actual OpenWebUI DB snapshot and mapping diagnostics.
- The initial browser request issue was reported as resolved, but its exact fix was not captured.
- Token-sync date formatting and page-size fixes were reported as applied; a successful end-to-end sync response and cache row count should still be recorded.
- Streamlit cache/runtime warnings were visible during FastAPI execution. They were not proven to cause the API failures.

## Safe future workflow

For each maintenance change:

1. Create a branch from the newest maintenance branch or the latest sanitized source baseline.
2. Capture the failing request, JSON body, backend traceback, and the smallest relevant functions.
3. Write down the expected source-of-truth behavior before editing.
4. Make the change on the closed-network server.
5. Run a focused validation and record its command/result without real employee data or secrets.
6. Export a sanitized patch or update this handoff with the exact applied behavior.
7. Commit code only when it has been transferred through an approved process.

Recommended validation cases:

- DB user + CSV mapping + usage
- DB user + CSV mapping + zero usage
- DB user without CSV match
- duplicate names without IDs
- CSV-only user or leader (must not appear as a dashboard user)
- LiteLLM page size at 100 and multiple pages
- upstream LiteLLM validation error body
- snapshot integrity failure and rollback

