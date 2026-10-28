# Maintainer and AI working agreement

Read `docs/MAINTENANCE_HANDOFF.md` before changing this repository.

## Source-of-truth rules

- New development on 2026-10-22: `backend_v2/` is the authoritative new API-backed implementation, not a reconstruction of the deployed legacy backend. Read `docs/OPENWEBUI_0123_API.md` and `backend_v2/README.md` before changes there. Do not ask for the old API contract to implement the official API collector.

- The closed-network development server contains the latest deployed source. The public GitHub `main` branch is an older Streamlit scaffold and must not be treated as a byte-for-byte copy of production.
- Do not reconstruct or overwrite deployed modules from screenshots. Ask for the smallest relevant function, traceback, response body, or sanitized diff.
- Mark every statement as one of: confirmed in deployed README/code, reported as applied, proposed only, or unresolved.
- Never commit secrets, API keys, internal IP addresses, employee data, database files, CSV contents, screenshots, or absolute internal paths.

## Product invariants

- OpenWebUI defines which users exist. New backend v2 uses its complete users API, without copying its DB file.
- The organization CSV enriches those DB users with division, team, position, and optional user ID.
- A CSV-only person must not be added to user/leader usage results.
- In v2, every DB user must remain in full user/leader lists and rankings even with zero usage in the selected period. Top 10 may show only the highest ten; full rankings must include zero-usage leaders.
- Ambiguous duplicate-name matches must remain visible as a mapping problem rather than being guessed.

## Change discipline

1. Identify whether the behavior belongs to OpenWebUI snapshot loading, organization mapping, user usage, token-log caching, category classification, or the React/FastAPI API layer.
2. Confirm the deployed function and its caller before proposing a patch.
3. Preserve the source-of-truth rules above.
4. Record validated fixes and remaining uncertainty in the maintenance handoff.
5. Validate API transport status separately from the JSON payload's `ok` field.


## UI conventions (user confirmed 2026-10-28)

- Use plain Korean user-facing copy. Do not put developer instructions, implementation details or future-development notices in normal screens. Put technical setup instructions in docs.
- The operations primary action is exactly 업데이트. No permanent refresh button on that screen; retry loading only after a fetch error.
- All visible text and chart fonts must be at least 14px (above 10pt). Reflow the layout rather than shrinking labels.
- Category charts place the chart on the left and the complete legend on the right, with no legend paging. Stack on narrow screens.
- No dashboard token control in the top bar. Retain configured server authentication via the separate optional login gate.
- Do not add execution-history export.
