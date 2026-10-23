# Campus Visual Design

## Direction

Campus uses an academic editorial identity: warm paper, deep green, precise rules, and expressive serif headings paired with a practical sans-serif interface. The architectural arch is a custom vector mark that represents an entrance to learning. The interface prioritizes records and tasks over decorative dashboards.

The redesign uses the installed `ui-ux-pro-max` skill. Its university research recommended an institutional palette, serif headings, a structured grid, and clear filtering. Its suggested portfolio layout was unsuitable for student registration and grade management, so the final layouts follow the actual workflows instead. Focused accessibility research informed table scrolling, keyboard navigation, and control labeling.

The [web-design-guidelines skill](https://github.com/vercel-labs/agent-skills/blob/main/skills/web-design-guidelines/SKILL.md) was read from its published source because it was not installed locally. The audit follows its [current interface guidelines](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md), adapted to Django's server-rendered, English-only interface.

## Existing application and scope

The application uses Django Templates, locally hosted Bootstrap 5.3, vanilla JavaScript, PostgreSQL, and WhiteNoise. The redesign preserves that stack. No business services, view authorization, models, migrations, route definitions, form validation, or database records are changed.

| Area | Pages and interactions |
| --- | --- |
| Shared shell | Desktop sidebar, mobile drawer, account link, POST logout, messages, skip link |
| Authentication | Sign-in, registration, password recovery, reset results, password changes |
| Account | Profile editing; pending, approved, and rejected application states |
| Dashboards | Role-specific counts, course records, recent grades, direct next actions |
| Courses | Search and semester filters, catalog, enrolled and archived courses, course details, enrollment and withdrawal confirmation |
| Teacher | Assigned courses, assessments, edit/delete confirmation, batch gradebook, final publication, CSV export |
| Administrator | People and applications, approval/rejection, blocking, teacher creation, academic structure, gradebooks, correction confirmations, audit history |
| Reports | Semester transcript, filters, CSV export, print layout |
| Supporting pages | Pagination, empty states, 403, 404, standalone 500, supplementary Django Admin |

The former interface had very small low-contrast text, decorative dashboard artwork, repeated card surfaces, and inconsistent information density. The new design gives content more hierarchy and reduces those decorative elements.

## Design tokens

The shared token source is `static/css/app.css`. The supplementary administration skin uses `static/css/admin.css` without importing Bootstrap into Django Admin.

| Token | Value | Purpose |
| --- | --- | --- |
| Paper | `#f5f3ed` | Application background |
| Surface | `#fffefa` | Record and form surfaces |
| Ink | `#24352f` | Primary text |
| Muted | `#5e6962` | Secondary text |
| Green | `#173d33` | Primary controls and navigation |
| Green hover | `#0b2b22` | Stronger interaction state |
| Green soft | `#e7eee6` | Selected and positive states |
| Rule | `#d7dcd3` | Non-interactive separators |
| Strong rule | `#7b887d` | Input boundaries and index text |
| Rust | `#a0472f` | Editorial accents and focus outline |
| Danger | `#a23130` | Errors and blocked states |
| Warning | `#775015` | Pending states |

Spacing follows a 4/8-based scale: 4, 8, 12, 16, 24, 32, 48, and 64 pixels. Shared padding, margins, and gaps use the corresponding custom properties. Buttons use a 3-pixel radius; record panels use 4 pixels. Only the mobile drawer uses an overlay shadow.

DM Sans provides interface text. Source Serif 4 provides headings and large numbers. Four font files and their SIL Open Font Licenses are hosted locally under `static/fonts/`; the interface requires no font CDN. Fonts use `font-display: swap`, and the primary interface font is preloaded. Numeric data uses tabular figures. Body text is 15 pixels, table text 13 pixels, and editable fields 16 pixels.

## Layout and component rules

- Use the dark green sidebar as the principal navigation anchor. Active destinations have both a visible rule and a selected background. Icons are consistent, decorative outline SVGs beside text labels.
- Keep the main canvas light. Separate data with thin rules and purposeful surfaces rather than shadows or gradients.
- Present dashboard totals as a single divided strip. Use only server-provided counts; do not invent graphs, activity, or trends.
- Present the course catalog as a numbered index with title, description, teacher, semester, capacity, and one navigation action. Avoid repeated ornamental cards.
- Keep forms to a readable width. Pair labels with controls, preserve server validation, and connect help/error descriptions to fields.
- Use real tables for academic records. Allow horizontal scrolling inside the table region. Overflowing regions receive an accessible name, visible keyboard focus, and keyboard scrolling.
- Keep the gradebook's student column visible on larger screens. On small phones, release the sticky column so it does not cover editable grades.
- Show current averages and published final grades as distinct information. The course detail result panel emphasizes the student's own results.
- Use standard links, forms, and buttons. Mutations retain CSRF-protected POST and their existing confirmation workflows.
- Submission feedback appears only after native validation succeeds. The submit control shows a waiting state and prevents duplicate submissions. Browser back navigation restores the control.
- Gradebook edits show a live unsaved-changes message and retain the navigation warning.

## Responsive behavior

The sidebar becomes a Bootstrap drawer below 992 pixels. The authentication page's editorial panel disappears below 768 pixels so the form becomes the main task. The course index collapses from three columns to two, with metadata below the title. Buttons and filters wrap naturally. Tables scroll locally without widening the document.

At wide desktop sizes, the student dashboard places recent grades beside course records. At smaller widths, the two sections stack. Dashboard totals become a two-column strip on phones. The transcript's print stylesheet removes navigation, filters, export buttons, and decorative surfaces.

## Accessibility and interaction

The implementation includes semantic page landmarks, one main heading, labeled controls, decorative icon hiding, named icon links, explicit table header scopes, a skip link, visible keyboard focus, accessible current navigation, native password-manager support, inline server errors, and a live gradebook status.

Primary actions have at least 44-pixel height. Native text inputs use 16-pixel text to prevent mobile input zoom. Nonessential transitions respect reduced-motion preferences. No animation, external image, chart library, or frontend framework was added.

Axe checks supplement visual and keyboard inspection; they do not establish complete assistive-technology compatibility. The interface deliberately retains consistent sentence-case labels and Django's configured English date formatting. React-specific hydration and client-router rules do not apply to this server-rendered application.

## Verification

Run the application with the README workflow, seed demonstration data explicitly, then run:

```sh
python scripts/browser_check.py
```

The browser check covers 1440, 1024, 768, and 375 pixel widths. It checks public authentication pages, error and empty states, all five demo account states, administrator forms, course details, gradebooks, assessment forms, and mobile navigation. It asserts successful page responses, one main heading, English document language, no document-wide horizontal overflow, and no JavaScript errors. Screenshots are saved under the ignored `test-results/` directory.

For an additional automated WCAG audit, provide a locally downloaded axe-core script:

```sh
BROWSER_AXE_SCRIPT=/absolute/path/to/axe.min.js python scripts/browser_check.py
```

No accessibility scanner is shipped to application users. Use `BROWSER_EXECUTABLE` to select an existing Chromium installation and `BROWSER_BASE_URL` to choose another running preview.

The completed findings and corrections are recorded in [Frontend Audit Results](ui-audit.md).
