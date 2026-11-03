# Deployment

## Local (default)

```bash
python3 run.py --seed --desktop
```

Data lives in `data/ticket_tracker.db` (SQLite). Copy that file to back up.

## Shared on the local network

```bash
python3 run.py --host 0.0.0.0
```

Sign-in is still required; everyone else on the network can reach the login
page, so only run this on a network you control.

## Hosted database (Postgres)

The data layer supports Postgres. Install a driver and point `DATABASE_URL`
at your instance:

```bash
pip install "psycopg[binary]"
export DATABASE_URL="postgres://user:password@host:5432/tickettracker"
python3 run.py
```

Schema is created automatically on first start (`db.init_schema()` plus
`db.migrate()` for upgrades).

## HTTPS in production

If the app is reachable beyond your LAN, put it behind a reverse proxy with
TLS (Caddy and nginx are common choices):

```
# Caddy example
tickets.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

Then run the app bound to localhost only (`python3 run.py` with the default
host) so all traffic goes through the proxy.

## Backups

- SQLite: copy `data/ticket_tracker.db` (the app also uses WAL, so include
  `ticket_tracker.db-wal` / `-shm` if present, or stop the server first).
- Postgres: use `pg_dump`.
- In-app: Settings → "Download full backup (JSON)" for records export.
