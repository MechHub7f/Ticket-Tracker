# Ticket Tracker

A meal-ticket system for senior-care facilities. Kitchen staff create daily
tickets for every resident and can add or remove meal items on many tickets at
once — with allergy and diet guardrails built in.

## Features

- **Tickets** — one ticket per resident per meal. Shows the date, resident
  name, allergies, diet restrictions, items, and notes.
- **Bulk actions** — select many tickets and add / remove / swap meal items on
  all of them in one step.
- **Allergy guard** — if an item conflicts with a resident's documented
  allergies or diet restrictions, the ticket is flagged and the change is
  blocked until someone with authority confirms it. Overrides are recorded.
- **Consent tracking** — allergies and diet restrictions can only be recorded
  after a consent date is on file (compliance requirement).
- **Activity log** — every significant change is recorded with who did it and
  when.
- **Role separation** — staff see active residents' tickets; administrators
  manage residents, medical data, accounts, and data retention.
- **Exports** — per-day CSV and a full JSON backup from the Settings page.

## Running

Requires Python 3.10+ (nothing else — the server is dependency-free).

```bash
python3 run.py --seed --desktop
```

- `--seed` adds demo residents, menu items, and tickets so you can click around
  (skipped automatically if data already exists).
- `--desktop` opens the app in a Chrome/Chromium app window when available.
- The app is served at http://127.0.0.1:8765. To let other computers on the
  local network use it: `python3 run.py --host 0.0.0.0`.

On first launch you create the administrator account in the browser.

## Tests

```bash
python3 tests/test_api.py
```

## Project layout

```
server/   HTTP server, database layer, business logic, auth
web/      Frontend (no build step), icons, service worker, manifest
tests/    Backend test suite
tools/    Helper scripts (icon generator)
data/     SQLite database lives here (never committed)
```

## Compliance

See [docs/COMPLIANCE.md](docs/COMPLIANCE.md) for how consent, audit logging,
access control, and data retention are implemented — and what your facility
still needs to do.

## Switching to a hosted database

The data layer supports Postgres as well. Point `DATABASE_URL` at a Postgres
instance (e.g. `postgres://user:pass@host:5432/tickettracker`) and install
`psycopg2-binary` if you want to run the server off-site. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
