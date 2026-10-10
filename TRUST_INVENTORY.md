# Asset and provider inventory — 16 September 2026

## Fonts
AlexBrush, DancingScript, GreatVibes, Pacifico and Sacramento embed SIL Open Font License 1.1 declarations in their name tables. Upstream licence texts are bundled in assets/fonts/licenses. Fonts are unchanged. Embedded GreatVibes copyright is 2010; the current upstream notice is 2015; preserve both as evidence rather than overwrite the font metadata.
Sources: https://github.com/google/fonts/tree/main/ofl (individual family directories).

## Visual assets
ICD brand images and custom offer logos are project-supplied; ownership was not independently established. Company logos are uploaded by organizations. Platform logos are brand identifiers, not proof of endorsement or partnership. Do not claim independent verification or redistribution rights. Before a public commercial launch, confirm ownership/permission for project-supplied logos and each third-party mark. No new stock photography or third-party illustration is introduced by this change.

## Data flow inventory
- Render: application hosting and operational requests/logs.
- Supabase: authentication, company/candidate data, applications and request/delivery tracking. Row-level policies isolate requests and company delivery records.
- Google sign-in through Supabase: account identity; no Gmail or Drive access implied.
- Groq, Cerebras, Gemini: configured AI providers and fallback; relevant resume text, job criteria and prompts can leave the app. Exact enabled providers depend on private runtime configuration.
- Configured SMTP / Google Apps Script integrations: recipient and recruitment message content; interview scheduling data where configured.
- LinkedIn: user-authorized job posting integration.
- Browser code: first-party scripts, optional local preferences disabled until chosen; no advertising/session-replay SDK added.
- Python dependency notices: generated from installed metadata during Docker build.

Provider accounts, retention settings and agreements are not independently certified. The app does not claim a completed legal or security certification.
