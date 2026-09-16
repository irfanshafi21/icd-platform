# ICD Platform review — 16 September 2026

## Owner dashboard improvements

- Company-filtered activity totals: jobs, applications, saved screenings, interviews, selections and average ATS.
- Thirty-day daily screening chart with readable daily counts, ATS distribution, hiring volumes and interview statuses.
- Company activity table and compact mobile cards with expandable contact/registration details.
- Explicit loading, unavailable, retry and empty states. Missing analytics never appears as zero activity.
- Owner authentication at the API and database function. Only aggregate activity leaves the database.

The activity endpoint requires `supabase/migrations/20260916090000_owner_activity_analytics.sql` to be applied to the hosted database. It is additive and does not modify recruitment records. The local SQL test verifies authorization, more than 1,500 records, cleared records, null scores, empty companies and the 30-day window.

## Important gaps to address next

| Priority | Finding | Practical next step |
| --- | --- | --- |
| High | Backups and a restore exercise are not activated in the project setup. | Configure encrypted private backups and test restoration in a separate database. Never put recruitment exports in public build artifacts. |
| High | Company sign-in uses a shared four-digit code. Durable throttling exists, but the code and credential-returning authentication design remain weak. | Move recruiters to individual authenticated accounts, company membership and roles; retire shared credential-returning flows through a planned migration. |
| High | Interview invitations run in an in-process background task. There is no durable delivery queue or owner-facing delivery history. | Save delivery jobs and status, retry failures safely, and allow an explicit resend. A restart must not silently lose queued invitations. |
| Medium | Rejection can erase candidate records, and clearing removes screenings from the active library. Lifetime reporting cannot be reconstructed from these tables. | Agree a retention policy, then record minimal non-identifying activity totals and an administrative audit trail. Keep the dashboard labelled as retained-record activity until then. |
| Medium | Offer documents and email sends have no persistent reporting history. | Record generation and delivery events so offers can be reported accurately; do not treat a selected candidate as an offer sent. |
| Medium | The availability workflow is documented as requiring activation on the default branch; alert preferences and staging also need operational setup. | Activate the existing health workflow and verify alerts. Establish a separate test environment before testing database changes against production. |

Evidence: `FREE_OPERATIONS_SETUP.md`, `.github/workflows/availability-check.yml`, owner authentication and interview/rejection/offer routes in `web_app.py`, and the committed database migrations. This is a focused source and workflow review, not a full security or legal audit.
