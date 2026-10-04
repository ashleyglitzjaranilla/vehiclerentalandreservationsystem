# Guest read-only access

**Date:** 2026-09-27
**Status:** Approved

## Problem

Every page in the app is behind `login_required`. Someone who only wants to look
at the fleet — a visitor, a reviewer, a colleague without an account — cannot see
anything at all. We want a read-only way in that does not involve handing out
credentials or creating accounts.

## Solution

A guest session: a button on the login page that grants a session with no user
behind it. A guest sees the same pages as a signed-in user, minus everything that
changes data.

### Roles

A session is in one of three states, derived from what is already in the session
cookie rather than stored a second time:

```python
def current_role() -> str | None:
    if session.get("user_id"): return "user"    # signed in
    if session.get("guest"):   return "guest"   # read-only
    return None                                  # anonymous
```

Deriving the role means sessions created before this change keep working without
a new key being present.

`POST /guest` sets `session["guest"] = True` and redirects to the dashboard.
`POST /logout` clears either kind of session.

### Decorators

`login_required` is replaced by two decorators, so each route states its intent:

- `viewer_required` — user or guest. Anonymous visitors are redirected to the
  login page with `?next=`, exactly as `login_required` does today.
- `editor_required` — user only. A guest gets `abort(403)`; an anonymous visitor
  is redirected to login.

### Routes

| Route | Guard |
| --- | --- |
| `/` dashboard | `viewer_required` |
| `/vehicles` | `viewer_required` |
| `/vehicles/<id>` (new) | `viewer_required` |
| `/search` | `viewer_required` |
| `/reports` | `viewer_required` |
| `/reports/export.csv` | `viewer_required` |
| `/vehicles/add` | `editor_required` |
| `/vehicles/<id>/edit` | `editor_required` |
| `/vehicles/<id>/delete` | `editor_required` |
| `/guest` (new, POST) | none |

`GET /vehicles/<id>` renders a new read-only `vehicle_detail.html` showing the
full record, including remarks and date acquired, which no page displays today.
Edit and Delete buttons appear on it only for editors. The page is shared with
signed-in users rather than being guest-only.

A new `403.html`, styled like the existing `404.html`, explains that the visitor
is browsing as a guest and offers Sign in and Back to dashboard.

### UI

- `base.html` — the sidebar and top bar render when `current_role` is set rather
  than when `current_username` is set, so guests get the normal chrome. When
  `is_guest`, a `no-print` amber strip sits above `main`: "Read-only mode — sign
  in to make changes", with a Sign in link. The sidebar footer shows a
  "Guest / read-only" pill, a Sign in button and an Exit guest button (POST to
  logout) in place of "Signed in as".
- `partials/_nav_links.html` — the link list gains an editor-only flag. Add
  Vehicle is not shown to guests.
- `partials/_vehicle_table.html` — the Actions column shows View for everyone,
  with Edit and Delete appended only when `is_editor`.
- `login.html` — below the sign-in button, a divider and a "Continue as guest"
  form posting to `/guest`.
- `dashboard.html` — the heading falls back to "Fleet overview" when there is no
  username.

The context processor exposes `current_role`, `is_guest` and `is_editor`
alongside the existing `current_username`.

### Testing

`conftest.py` gains a `guest_client` fixture that posts to `/guest`.
`tests/test_guest.py` covers:

- a guest reaches the dashboard, vehicle list, detail page, search, reports and
  the CSV export;
- a guest gets 403 on GET add, GET edit, GET delete and POST delete;
- the vehicle table renders no Edit link for a guest but does for a signed-in
  user;
- `/guest` followed by `/logout` returns the session to anonymous.

Existing tests are unaffected: `viewer_required` keeps the anonymous-redirect
behaviour `login_required` had.

## Out of scope

No guest `User` row, no rate limiting, no per-field hiding of remarks, and no
separate public URL prefix. A guest sees whole records or nothing.
