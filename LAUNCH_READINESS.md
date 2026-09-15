# Launch readiness — 15 September 2026

## Implemented locally, not deployed
- Help/FAQ and support contact at /help.
- Cookies/device-storage explanation at /cookies and /help#device.
- Offline banner; does not retry submissions or claim disconnected work is saved.
- Screening outcome summary, with file rejection distinguished from a hiring decision.

## Must resolve before a complete compliance claim
- Confirm legal operator, country, business/support address and paid-service model.
- Review TERMS_DRAFT.md with appropriate legal advice, including applicable consumer and employment rules.
- Inventory all browser storage, especially persisted AI history, and implement optional-storage controls. Do not label every local-storage feature strictly necessary.
- Generate third-party notices from the exact deployment environment, including transitive dependencies and bundled fonts/assets. requirements.txt is not a complete license inventory.
- Security review: authentication, tenant separation, throttling, session revocation, secrets, database access policies, dependency versions and upload handling. Existing controls are not certification.
- External alerting/crash monitoring needs an account, destination and retention decision. Do not send résumés, prompts, contact details, access codes or session tokens to telemetry.
- Verify hosting/database backup plan and retention. Enable scheduled encrypted backups with an approved private destination; include database, stored files and configuration. Do not place dumps in Git or public CI artifacts.
- Restore into an isolated non-production environment; verify record counts, tenant isolation and file retrieval. Record restore time and recovery point, then schedule repeat drills. Never test a restore over production.

## Not needed for current features
- Camera and location prompts: app does not use these features.
- Browser push prompts: current notifications are in-app.
- Advertising/session replay: not required to operate recruitment workflows.
- Product return/shipping policy: no physical-goods workflow.
- Native-app EULA/app-store permissions: this is currently a web app.

Refund/cancellation terms depend on whether paid subscriptions or services exist; do not invent a no-refund policy.
No external monitoring or backup automation has been activated by this implementation.
