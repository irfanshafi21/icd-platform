# Free-only operations

No paid services have been enabled.

## Ready in source
- Quality checks on pull requests and the deployment branch, using public-repository standard GitHub runners.
- Six-hour health check workflow; schedule activation requires merging the workflow into the default branch (currently main). Failure notifications require GitHub Actions notifications enabled for the owner. This is not real-time crash telemetry.
- Python dependency notices generated during the Docker build from installed distribution metadata and included licence texts. Bundled fonts/images/JavaScript still need a separate rights inventory.

## Backups — not activated
Need an approved private storage destination, database connection credentials and an encryption key held outside the repository. Do not send passwords in chat. A local encrypted backup is free but requires the computer to be running; off-site storage improves recoverability.
Do not put database exports, candidate files, internal company credentials or encryption keys into GitHub artifacts/public logs.
Back up database schemas/data and uploaded files. Test restore only in a separate database. No production restore is authorized by a routine test.

## Remaining decisions
- Private backup destination and secure credential configuration.
- Separate staging database/hosting availability within free account limits.
- Retention duration per recruitment record, before any automatic deletion.
- Full removal of credential-returning company RPCs requires an authentication migration. Current code adds durable throttling but does not eliminate that architectural risk.
- Independent Indian legal review cannot be supplied or certified by app code.

## Active database safeguard
10 company-login attempts per 15-minute window, shared by both code-verification paths. Concurrent attempts serialize on a database row. Blocked attempts do not extend the window. This can also temporarily block legitimate users of the same company; four digits remain a limited-strength credential.
Verification covered valid login, blocked attempts, shared budget and expiry in a rolled-back transaction.
