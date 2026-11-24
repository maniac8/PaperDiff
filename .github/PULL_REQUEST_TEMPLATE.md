## Summary

<!-- Briefly explain what this PR changes and why. Link related issues (e.g. Fixes #123). -->

## Checklist

- [ ] Target branch is `dev` (only Release PRs from `dev` or urgent `hotfix/*` PRs target `main`)
- [ ] Backend tests pass: `cd paperdiff && python3 -m pytest -W ignore -v`
- [ ] Frontend unit tests & build pass: `cd paperdiff/frontend && node --experimental-strip-types --test src/utils/*.test.mjs && npm run build`
- [ ] License & privacy hygiene: no GPL/AGPL dependencies, no outbound network/telemetry calls, no personal manuscript data or hardcoded `/Users/` paths
- [ ] Verified contrast across Light / Sepia / Dark themes (if UI changed)
- [ ] Added or updated unit tests covering the new behavior or bug fix
