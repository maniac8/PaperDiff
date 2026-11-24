# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :--- |
| `0.1.x` | Yes |
| `< 0.1.0` | No |

## Local-First Security & Privacy Model

PaperDiff is designed as a **100% local-first, offline application**:

- **Loopback-only binding**: The embedded FastAPI server binds exclusively to `127.0.0.1` and never makes outbound network requests, external LLM API calls, or telemetry uploads.
- **Local workspace root sandbox**: Local folder bindings resolve canonical paths (`realpath`) and block path traversal (`..`) and symlinks escaping the bound workspace root.
- **Safe write policy**: Saving edits defaults to writing a `_revised` sibling copy; in-place overwrites automatically create a `.paperdiff.bak` backup first.
- **CSRF & origin guards**: Sensitive local endpoints (such as graceful server shutdown and CLI path handoff) enforce loopback checks and explicit request headers.

## Reporting a Vulnerability

If you discover a security issue (for example, path-traversal bypass, XSS/HTML injection in document rendering or PDF export, or unsafe archive extraction):

1. **Do not open a public GitHub Issue.**
2. Report it privately through [GitHub Security Advisories](https://github.com/maniac8/PaperDiff/security/advisories/new).
3. Please include reproduction steps and a minimal anonymized sample (never attach private unpublished manuscripts).

We aim to acknowledge reports within 72 hours and coordinate a fix via a `hotfix/*` release.
