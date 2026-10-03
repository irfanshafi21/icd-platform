# Security review — 15 September 2026

Partial review, not certification. No production records changed.

## Mitigation applied 15 September 2026
The credential lookup and verification functions now share a durable 10-attempt/15-minute company limit. Valid login, limit enforcement, shared budget and expiry were verified with rolled-back test writes. This mitigates guessing but does not remove the credential-returning architecture described below.

## Original live findings
- Public get_company_login(company_id, code) returns internal auth credentials upon a matching four-digit code. Its SQL body has no throttling. API-only rate limits can be bypassed via direct database RPC calls. Priority: high.
- Public verify_company_access_code is also an unthrottled code oracle and does not check approval status.
- owner_company_profiles uses definer privileges, but its definition explicitly filters on the owner's signed JWT email. Do not blindly change to invoker privileges without verifying the owner workflow.
- registration_tracking_attempts has RLS and no policies: this may be intentionally inaccessible except through controlled functions.
- Other privileged RPC grants and disabled leaked-password protection require follow-up.

## Required login remediation
Preserve user-facing four-digit codes only behind a server-controlled, durable throttling layer. Remove anonymous access to credential-returning/code-verification RPCs once the server authentication replacement has been staged and tested. Never revoke the existing login path before its replacement is ready. Rotate underlying company credentials after migration. Test concurrency, distributed attempts, approval status and revoked sessions.

## Still not activated or certified
External monitoring, encrypted scheduled backups and restore drill, dependency/licence inventory, optional-storage controls, deletion/retention automation and independent legal/security review.

## Release protection added locally
GitHub Actions regression workflow uses mock data and no production secrets. It does not automatically configure branch protection or prevent Render auto-deploying a failed revision; those hosting settings must be configured separately.
