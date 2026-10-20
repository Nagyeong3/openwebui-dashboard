# Maintenance session log — 2026-10-20

This log records what was learned during remote troubleshooting. It intentionally excludes screenshots, internal addresses, employee data, credentials, and unverified reconstructed source.

## Confirmed from inspected server screenshots

- The deployed system is newer than the public repository and includes a React/FastAPI migration alongside the legacy Streamlit application.
- OpenWebUI data is consumed through a validated local snapshot rather than by querying the live DB continuously.
- LiteLLM spend logs are synchronized to a local token cache DB.
- Organization data is merged through `org_mapping` logic, with ID-first and unique-name fallback matching.
- User usage, token usage, team metrics, reports, and category classification use separate service modules.
- The analytics loader already enriches DB users with the organization CSV.

## Reported as applied on the development server

- LiteLLM spend-log dates changed to the endpoint-compatible date-time representation.
- LiteLLM spend-log request page size is capped at 100.
- Team filter values became visible on token usage and user-status screens after filter-option work.

These items were reported by the maintainer but were not verified against a complete source export or automated test run.

## Explicitly not applied

- No change was made to append CSV-only leaders/users to user-status results.
- No duplicate `enrich_users_with_org` call was added to `user_service.py` after confirming enrichment already happens in the analytics loader.

## Decisions

- OpenWebUI DB remains the user authority.
- CSV remains an enrichment source and may provide organization filter values or explicit staffing counts, but does not create dashboard users.
- Future AI work must use this record as context and request sanitized code fragments from the deployed server instead of assuming public `main` is current.

## Next evidence to collect

- Sanitized diff of the final filter-option changes.
- End-to-end successful `/api/tokens/sync` JSON response and resulting cache statistics.
- Mapping diagnostics for a DB leader who should appear with zero usage.
- A sanitized current tree listing and dependency versions from the closed-network server.

