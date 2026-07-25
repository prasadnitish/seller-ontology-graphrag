# Security policy

Report vulnerabilities privately to the repository owner. Do not include credentials, customer
data, or exploit payloads in a public issue.

## Supported surface

The current supported surface is the latest default branch.

## Deployment checklist

- Use only synthetic or explicitly approved source data.
- Keep `GRAPHKIT_PUBLIC=true` for hosted read-only APIs.
- Set `GRAPHKIT_ALLOWED_HOSTS` to the exact deployed hostname or hostnames.
- Confirm `/api/workspace/*` returns 404 in public mode.
- Confirm `/docs`, `/redoc`, and `/openapi.json` return 404 in public mode.
- Verify CSP and the other security response headers at the hosting edge.
- Terminate TLS at the hosting layer.
- Store Neo4j and provider credentials in the host secret manager.
- Use a Neo4j account with the minimum read permission for public query traffic.
- Keep database-level tenant constraints and result limits.
- Add upstream rate limiting and request-size limits.
- Do not enable public uploads.
- Run secret scanning and dependency review before release.
- Verify the exact evidence manifest before publishing metrics.

The local editor uses loopback binding, a same-site HttpOnly session cookie, and a per-launch CSRF
token. It is not a multi-user authentication system.
