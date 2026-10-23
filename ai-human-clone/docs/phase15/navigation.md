# Phase 15: mobile navigation, responsive layout, forms and accessibility

## Mobile navigation

The app frame is `components/mobile/MobileShell.tsx`, rendered once by `app/layout.tsx`.

| Screen width | Top | Bottom |
| --- | --- | --- |
| below `md` (< 768px) | `MobileTopBar`: back button on nested pages, logo + page title, menu button that opens a drawer | `BottomNav` (logged-in users only, hidden on full-height screens) |
| `md` and up | `Navbar`: Dashboard, Clones, Explore, Analytics, Profile, **More** (Organizations, Billing, Developer, Admin), Logout | none |

The rules (which tab is active, where the bottom nav hides, what the back button
points to, which links a user gets) live in `lib/navigation.ts` with no React/DOM
imports. They are tested in `tests/navigation.test.ts`.

### Bottom navigation

Home (`/dashboard`), Clones (`/clones`), Chat, Analytics (`/analytics`), Profile (`/profile`).

- **Chat** opens the last clone chat the user opened (`/clone/[id]`). The id is
  kept in `localStorage` under `ahc:last-chat:<userId>`, so each account on a
  shared device has its own. Reads and writes are wrapped in try/catch, only
  plain ids are accepted, and the value is cleared on logout. With nothing
  stored, Chat goes to `/clones`.
- Active tab: `aria-current="page"`, an indicator bar, an accent icon and a bold
  label, so it doesn't rely on colour alone.
- Each target is at least 44px tall. The bar is 4rem plus
  `env(safe-area-inset-bottom)`, and the page gets the same bottom padding
  (`.pb-bottom-nav`), so content never ends up behind it.
- Hidden on full-height screens (`/clone/[id]` chat, `/clone/[id]/call`, the old
  `/clone/[id]/chat` redirect, `/c/[slug]`), for anonymous visitors, and while
  the session is still loading.

### Top bar and drawer

- **Back button** (logical parent, not browser history):
  `/clone/[id]/{edit,knowledge,memory,voice,avatar,sharing,call,analytics}` go to `/clone/[id]/details`;
  `/clone/[id]/knowledge/[doc]` goes to `.../knowledge`; `/clone/[id]` and `/clone/[id]/details` go to `/clones`;
  `/create-clone` goes to `/dashboard`; `/c/[slug]` goes to `/explore`;
  `/organizations/[id]` goes to `/organizations`; `/organizations/[id]/*` goes to `/organizations/[id]`;
  `/developer/*` goes to `/developer`; `/admin/*` goes to `/admin/dashboard` (and `/admin/system/errors` to `/admin/system`).
- **Drawer** (logged in): Explore, Organizations, Billing, Developer, Admin (only
  if `user.is_admin`; the API still checks), Logout. It is a `role="dialog"` with
  `aria-modal="true"`. Focus moves into it and stays there (Tab wraps), and
  Escape, the overlay or the close button closes it. Focus then returns to the
  menu button. The page behind doesn't scroll, and the drawer closes if the
  window grows to `md`.
- **Anonymous visitors** get a simpler bar: Explore, Login and Create Account.
  Below 400px, Explore moves into the menu, and below 360px the button reads
  "Sign up".
- The desktop "More" menu opens on click or keyboard, never on hover. It closes
  on Escape, an outside click or focus leaving it.
- A "Skip to content" link targets `#main-content`.

### Frame sizes for full-height screens

`globals.css` defines `--app-header-h: calc(4rem + env(safe-area-inset-top))`
and `--app-bottom-nav-h`. Full-height screens should use
`h-[calc(100dvh-var(--app-header-h))]` rather than `100dvh-4rem`, so that
notched phones in standalone mode fit too.

## Responsive breakpoints tested

Target widths: 320, 360, 375, 390, 414, 768px and desktop (1280px). The layouts
were reviewed in code at these widths, and screenshots come from the release build.
Fixes:

- **Landing**: smaller hero type below 375px, full-width 48px CTAs, a footer nav.
  The footer now sits outside `<main>`.
- **Login / Register**: tighter card padding on phones, 16px inputs.
- **Dashboard and /clones**: a shared `MyCloneCard` with avatar (lazy image or
  initials), name, status and visibility badges (text), a big **Chat** button,
  and Edit, Analytics (`/clone/[id]/analytics`), Details and Share in a 2-column
  grid. Delete appears on the dashboard. `/clones` shows "My Clones" for
  logged-in users, then public clones (which link to `/c/[slug]`).
- **Profile**: long emails wrap instead of being cut off; 44px+ buttons.
- **Create / Edit / Details**: 2-column action grid on phones, Analytics link,
  larger skill-remove buttons, a check mark on selected choices, and focus moves
  to the first invalid field.
- **Explore**: 2-column filter grid on phones, a search input, 44px pagination.
- **Public clone page**: avatar beside the name, and "Share this AI Clone"
  (Web Share API, falling back to copying the link) next to Start Chat.
- **Admin / Developer**: the sidebar becomes a horizontally scrolling tab row
  (`components/mobile/SectionNav.tsx`) that scrolls the current tab into view.
  The page itself never scrolls sideways. The admin `<Table>` keeps its API: below
  `md`, each row becomes a stacked card with "column: value" lines (`data-label`
  is added to each `<td>` automatically; empty action cells are hidden). Code
  blocks scroll inside their own box. The "key shown once" flow is unchanged:
  full keys exist only in component state.
- **ConfirmDialog**: a full-width bottom sheet with 48px buttons on phones and a
  centered card from `sm` up.

## Forms

- Inputs use the right type, `autoComplete`, `inputMode`, `enterKeyHint`, and
  `autoCapitalize`/`spellCheck` (email, username, password, url, search).
- `Field` adds `aria-invalid` and `aria-describedby` (pointing to the inline
  error) to its control. Errors show an icon as well as colour.
- Values stay as typed after validation or API errors. Submit buttons show
  busy text and are disabled while saving, and success uses
  `FormAlert kind="success"` (`role="status"`).
- Inputs are 16px below `md` (an unlayered rule in `globals.css`), which stops
  iOS from zooming in on focus.

## Accessibility

- Landmarks: one `<header>`/`<nav aria-label>` per breakpoint, page `<main>`,
  named sub-navigation (`Admin`, `Developer`, `Pages`) and a footer nav.
- `aria-current="page"` on every active nav item: bottom nav, drawer, desktop
  bar, More menu, admin and developer tabs.
- A visible `:focus-visible` outline everywhere, and reduced motion respected.
- Status is never shown by colour alone: badges carry text, alerts carry ⚠/✓,
  public chat availability is written out, and a disabled Chat says "disabled".
- Avatar images are lazy (`loading="lazy"`, `decoding="async"`,
  `referrerPolicy="no-referrer"`) and fall back to initials if they fail.
- The shell imports no admin or developer code. Icons are inline SVG, with no
  icon library.
