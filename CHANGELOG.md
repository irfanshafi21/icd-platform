# Changelog

## 2026-09-09

- Rebuilt candidate and recruiter access pages with a cleaner two-surface composition, stronger hierarchy, compact forms, improved organization cards, and responsive mobile layouts.
- Removed the redundant focus capsule around resume-screening range controls while preserving a precise accessible focus state.

## 2026-09-08

- Redesigned the screening role picker into compact searchable role cards and rebuilt screening priorities as dense, custom-themed percentage controls.
- Rebuilt the complete resume-screening studio: premium hero and steps, refined criteria and role picker, stronger upload and scoring controls, sticky desktop actions, responsive results cards, and mobile-specific layout.
- Rebuilt notifications as a premium activity centre with a high-contrast header, distinct event cards, stronger unread treatment, sticky actions, contained scrolling, and a mobile bottom sheet.
- Redesigned recruiter candidate cards as a compact premium Jobs-style component with reduced empty space, balanced evidence, sharper hierarchy, and a unified action tray.
- Fixed the transformed interview-eligibility action so it retains a full candidate-card grid column instead of collapsing into the overflow-button column.
- Rebuilt recruiter candidate cards on the exact Jobs-card structure with matching dimensions, header, metadata spacing, action tray, and candidate-specific ATS/rank emphasis.
- Enforced accessible text/background contrast for primary, secondary, danger, and floating-AI controls across every normal and hover state.
- Added a live AI interview companion that opens beside Google Meet and automatically loads evidence-grounded questions for the selected candidate.
- Contained the interview delete action inside every card and removed the desktop/mobile grid overflow that clipped it against the control rail.
- Fixed candidate overflow actions so desktop menus remain visible and mobile actions open as a readable bottom sheet; consolidated notifications into a vertical, viewport-safe activity panel.
- Emphasized candidate score and rank badges and made the floating AI assistant always reveal the newest answer.
- Simplified recruiter candidate cards to exactly mirror the Jobs-card hierarchy, moving secondary evidence and actions behind the profile and overflow menu.
- Standardized Jobs, recruiter Candidates, and Candidate Portal opportunities into three-column desktop cards, reduced global headers, and rebuilt interview rows to use the full schedule width.
- Made AI Insights move to and focus the beginning of each generated answer, and restored the mobile recruiter back button.
- Added production UI quality controls for accessible focus, contrast, touch targets, form fields, loading feedback, notifications, responsive behavior, and reduced motion.
- Applied a product-wide visual system to every recruiter page and access portal, and converted AI interview preparation into a side workspace on desktop.
- Introduced a more distinctive premium card system across recruiter jobs and candidates, candidate opportunities and applications, and owner company governance.
- Corrected the remaining mobile KPI collision, job action-menu clipping, and downstream interview-score synchronization error.
- Prevented an optional candidate-portal status sync failure from reporting a successfully saved interview score as failed.
- Corrected mobile job KPI overlap, interview control-panel contrast, locked-score styling, and button hover colors.
- Refined the Jobs, Resume Screening, AI Insights, Offer Letters, Candidate Portal, and Owner Portal surfaces.
- Removed the unused résumé-inbox and LinkedIn connection information from company settings.
