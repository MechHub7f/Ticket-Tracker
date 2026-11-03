"""HTTP API routes for Ticket Tracker."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Callable

from . import auth, services
from .db import Database


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class Ctx:
    def __init__(self, db: Database, method: str, path: str, query: dict, body: dict,
                 user: dict | None, token: str | None, client_ip: str):
        self.db = db
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.user = user
        self.token = token
        self.client_ip = client_ip
        self.headers: list[tuple[str, str]] = []

    def require_user(self) -> dict:
        if not self.user:
            raise ApiError("Please sign in", 401)
        return self.user

    def require_admin(self) -> dict:
        user = self.require_user()
        if user["role"] != "admin":
            raise ApiError("Only an administrator can do that", 403)
        return user


# ---------------------------------------------------------------- helpers
def _int(value: Any, name: str = "id") -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(f"{name} must be a number")


def _ids(value: Any, name: str = "tickets") -> list[int]:
    if not isinstance(value, list):
        raise ApiError(f"{name} must be a list")
    try:
        return [int(v) for v in value]
    except (TypeError, ValueError):
        raise ApiError(f"{name} must contain numbers")


def _str(value: Any, name: str = "value", allow_empty: bool = True) -> str:
    text = str(value or "").strip()
    if not allow_empty and not text:
        raise ApiError(f"{name} is required")
    return text


def _bool(value: Any) -> bool:
    return value in (True, 1, "1", "true", "on", "yes")


def _chunks(seq: list, size: int):
    for start in range(0, len(seq), size):
        yield seq[start : start + size]


# ---------------------------------------------------------------- auth
def auth_status(ctx: Ctx):
    return 200, {
        "setup_required": auth.user_count(ctx.db) == 0,
        "user": ctx.user,
    }


def auth_setup(ctx: Ctx):
    if auth.user_count(ctx.db) > 0:
        raise ApiError("Setup has already been completed", 409)
    username = _str(ctx.body.get("username"), "Username", allow_empty=False)
    password = _str(ctx.body.get("password"), "Password", allow_empty=False)
    display_name = _str(ctx.body.get("display_name")) or username
    auth.create_user(ctx.db, username, password, display_name, "admin")
    token, user = auth.login(ctx.db, username, password)
    services.audit(ctx.db, user["id"], "setup", f"Created admin account {username}")
    return 201, {"user": user, "token": token}


LOGIN_FAILURES: dict[str, list[float]] = {}


def auth_login(ctx: Ctx):
    import time

    failures = [t for t in LOGIN_FAILURES.get(ctx.client_ip, []) if time.time() - t < 300]
    if len(failures) >= 8:
        raise ApiError("Too many failed sign-ins. Try again in a few minutes.", 429)
    username = _str(ctx.body.get("username"))
    password = str(ctx.body.get("password") or "")
    try:
        token, user = auth.login(ctx.db, username, password)
    except ValueError:
        failures.append(time.time())
        LOGIN_FAILURES[ctx.client_ip] = failures
        raise ApiError("Incorrect username or password", 401)
    LOGIN_FAILURES.pop(ctx.client_ip, None)
    services.audit(ctx.db, user["id"], "login", f"{user['username']} signed in")
    return 200, {"user": user, "token": token}


def auth_logout(ctx: Ctx):
    auth.logout(ctx.db, ctx.token)
    return 200, {"ok": True}


def auth_me(ctx: Ctx):
    return 200, {"user": ctx.require_user()}


# ---------------------------------------------------------------- bootstrap
def bootstrap(ctx: Ctx):
    user = ctx.require_user()
    items = services.list_items(ctx.db, active=1)
    categories = ctx.db.query(
        "SELECT DISTINCT category FROM meal_items ORDER BY LOWER(category)"
    )
    return 200, {
        "user": user,
        "today": services.today_iso(),
        "buildings": services.list_buildings(ctx.db),
        "items": items,
        "categories": [row["category"] for row in categories],
        "meals": [{"value": m, "label": services.MEAL_LABELS[m]} for m in services.MEALS],
        "statuses": [{"value": s, "label": services.STATUS_LABELS[s]} for s in services.STATUSES],
        "meal_labels": services.MEAL_LABELS,
        "status_labels": services.STATUS_LABELS,
    }


# ---------------------------------------------------------------- buildings
def buildings_list(ctx: Ctx):
    ctx.require_user()
    return 200, {"buildings": services.list_buildings(ctx.db)}


def buildings_create(ctx: Ctx):
    ctx.require_admin()
    services.create_building(ctx.db, ctx.body)
    return 201, {"buildings": services.list_buildings(ctx.db)}


def buildings_update(ctx: Ctx):
    ctx.require_admin()
    services.update_building(ctx.db, _int(ctx.params["id"]), ctx.body)
    return 200, {"buildings": services.list_buildings(ctx.db)}


def buildings_delete(ctx: Ctx):
    ctx.require_admin()
    services.delete_building(ctx.db, _int(ctx.params["id"]))
    return 200, {"buildings": services.list_buildings(ctx.db)}


# ---------------------------------------------------------------- residents
def residents_list(ctx: Ctx):
    ctx.require_user()
    active = ctx.query.get("active")
    if active == "all":
        ctx.require_admin()  # historical/inactive residents: admin only
    building_id = ctx.query.get("building_id")
    residents = services.list_residents(
        ctx.db,
        q=_str(ctx.query.get("q")),
        building_id=_int(building_id) if building_id else None,
        active=None if active == "all" else (1 if active in (None, "", "1") else 0),
    )
    return 200, {"residents": residents}


def residents_create(ctx: Ctx):
    ctx.require_admin()  # resident profiles hold medical data: admins only
    resident_id = services.create_resident(ctx.db, ctx.body)
    services.audit(
        ctx.db,
        ctx.user["id"],
        "resident.create",
        f"{ctx.body.get('name', '')} (consent: {ctx.body.get('consent_date') or 'none'})",
    )
    return 201, {"id": resident_id}


def residents_get(ctx: Ctx):
    ctx.require_user()
    resident = services.get_resident(ctx.db, _int(ctx.params["id"]))
    if not resident:
        raise ApiError("Resident not found", 404)
    return 200, {"resident": resident}


def residents_update(ctx: Ctx):
    ctx.require_admin()  # medical data edits: admins only
    resident_id = _int(ctx.params["id"])
    before = services.get_resident(ctx.db, resident_id)
    services.update_resident(ctx.db, resident_id, ctx.body)
    after = services.get_resident(ctx.db, resident_id)
    changed = []
    for key in ("name", "room", "allergies", "diet", "notes", "consent_date", "active"):
        old = str((before or {}).get(key, ""))
        new = str((after or {}).get(key, ""))
        if old != new:
            if key in ("allergies", "diet"):
                changed.append(f"{key} updated")
            else:
                changed.append(f"{key}: '{old}' -> '{new}'")
    services.audit(
        ctx.db,
        ctx.user["id"],
        "resident.update",
        f"{after['name'] if after else resident_id}: " + ("; ".join(changed) or "no changes"),
    )
    return 200, {"ok": True}


def residents_delete(ctx: Ctx):
    ctx.require_admin()
    resident_id = _int(ctx.params["id"])
    resident = services.get_resident(ctx.db, resident_id)
    services.delete_resident(ctx.db, resident_id)
    services.audit(
        ctx.db, ctx.user["id"], "resident.delete", resident["name"] if resident else str(resident_id)
    )
    return 200, {"ok": True}


# ---------------------------------------------------------------- menu items
def items_list(ctx: Ctx):
    ctx.require_user()
    return 200, {"items": services.list_items(ctx.db, q=_str(ctx.query.get("q")))}


def items_create(ctx: Ctx):
    ctx.require_user()
    item_id = services.create_item(ctx.db, ctx.body)
    services.audit(ctx.db, ctx.user["id"], "item.create", ctx.body.get("name", ""))
    return 201, {"id": item_id}


def items_update(ctx: Ctx):
    ctx.require_user()
    services.update_item(ctx.db, _int(ctx.params["id"]), ctx.body)
    return 200, {"ok": True}


def items_delete(ctx: Ctx):
    ctx.require_admin()
    item = services.get_item(ctx.db, _int(ctx.params["id"]))
    services.delete_item(ctx.db, _int(ctx.params["id"]))
    services.audit(ctx.db, ctx.user["id"], "item.delete", item["name"] if item else "")
    return 200, {"ok": True}


# ---------------------------------------------------------------- tickets
def tickets_list(ctx: Ctx):
    ctx.require_user()
    tickets = services.list_tickets(
        ctx.db,
        service_date=ctx.query.get("date") or None,
        date_from=ctx.query.get("date_from") or None,
        date_to=ctx.query.get("date_to") or None,
        meal=ctx.query.get("meal") or None,
        building_id=_int(ctx.query["building_id"]) if ctx.query.get("building_id") else None,
        status=ctx.query.get("status") or None,
        q=ctx.query.get("q") or None,
        resident_id=_int(ctx.query["resident_id"]) if ctx.query.get("resident_id") else None,
        # Least privilege: staff only see tickets for currently active residents.
        active_only=ctx.user["role"] != "admin",
    )
    return 200, {
        "tickets": tickets,
        "meal_labels": services.MEAL_LABELS,
    }


def tickets_create(ctx: Ctx):
    ctx.require_user()
    ticket_id = services.create_ticket(ctx.db, ctx.body)
    return 201, {"id": ticket_id, "ticket": services.get_ticket(ctx.db, ticket_id)}


def tickets_get(ctx: Ctx):
    ctx.require_user()
    ticket = services.get_ticket(ctx.db, _int(ctx.params["id"]))
    if not ticket:
        raise ApiError("Ticket not found", 404)
    return 200, {"ticket": ticket}


def tickets_update(ctx: Ctx):
    ctx.require_user()
    services.update_ticket(ctx.db, _int(ctx.params["id"]), ctx.body)
    return 200, {"ticket": services.get_ticket(ctx.db, _int(ctx.params["id"]))}


def tickets_delete(ctx: Ctx):
    ctx.require_user()
    services.delete_ticket(ctx.db, _int(ctx.params["id"]))
    return 200, {"ok": True}


def tickets_add_item(ctx: Ctx):
    ctx.require_user()
    warnings = services.add_item_to_ticket(
        ctx.db,
        _int(ctx.params["id"]),
        _int(ctx.body.get("item_id"), "item_id"),
        _int(ctx.body.get("qty") or 1, "qty"),
    )
    return 200, {"warnings": warnings, "ticket": services.get_ticket(ctx.db, _int(ctx.params["id"]))}


def tickets_set_item(ctx: Ctx):
    ctx.require_user()
    services.set_ticket_item(
        ctx.db,
        _int(ctx.params["id"]),
        _int(ctx.params["item_id"], "item_id"),
        _int(ctx.body.get("qty"), "qty"),
    )
    return 200, {"ticket": services.get_ticket(ctx.db, _int(ctx.params["id"]))}


def tickets_remove_item(ctx: Ctx):
    ctx.require_user()
    services.remove_item_from_ticket(
        ctx.db, _int(ctx.params["id"]), _int(ctx.params["item_id"], "item_id")
    )
    return 200, {"ticket": services.get_ticket(ctx.db, _int(ctx.params["id"]))}


def tickets_generate(ctx: Ctx):
    ctx.require_user()
    result = services.generate_tickets(
        ctx.db,
        service_date=ctx.body.get("date") or services.today_iso(),
        meals=ctx.body.get("meals") or None,
        building_ids=ctx.body.get("building_ids") or None,
        resident_ids=ctx.body.get("resident_ids") or None,
    )
    services.audit(
        ctx.db,
        ctx.user["id"],
        "tickets.generate",
        f"{result['created']} tickets on {result['date']}",
    )
    return 200, result


# ---------------------------------------------------------------- bulk
def bulk_add(ctx: Ctx):
    user = ctx.require_user()
    result = services.bulk_add_items(
        ctx.db,
        _ids(ctx.body.get("ticket_ids")),
        _ids(ctx.body.get("item_ids"), "items"),
        qty=_int(ctx.body.get("qty") or 1, "qty"),
        dry_run=_bool(ctx.body.get("dry_run")),
        force=_bool(ctx.body.get("force")),
    )
    if result.get("applied"):
        services.audit(
            ctx.db,
            user["id"],
            "tickets.add_items",
            f"{result['items']} items to {result['tickets']} tickets",
        )
    return 200, result


def bulk_remove(ctx: Ctx):
    user = ctx.require_user()
    remove_all = _bool(ctx.body.get("remove_all"))
    qty = ctx.body.get("qty")
    result = services.bulk_remove_items(
        ctx.db,
        _ids(ctx.body.get("ticket_ids")),
        _ids(ctx.body.get("item_ids"), "items"),
        qty=None if qty in (None, "") else _int(qty, "qty"),
        remove_all=remove_all,
    )
    services.audit(
        ctx.db,
        user["id"],
        "tickets.remove_items",
        f"{result['tickets']} tickets, {result['items']} items",
    )
    return 200, result


def bulk_replace(ctx: Ctx):
    user = ctx.require_user()
    result = services.bulk_replace_item(
        ctx.db,
        _ids(ctx.body.get("ticket_ids")),
        _int(ctx.body.get("from_item_id"), "from_item_id"),
        _int(ctx.body.get("to_item_id"), "to_item_id"),
        dry_run=_bool(ctx.body.get("dry_run")),
        force=_bool(ctx.body.get("force")),
    )
    if result.get("applied"):
        services.audit(
            ctx.db,
            user["id"],
            "tickets.replace_item",
            f"{result['from_item']} -> {result['to_item']} on {result['tickets']} tickets",
        )
    return 200, result


def bulk_status(ctx: Ctx):
    user = ctx.require_user()
    result = services.bulk_set_status(
        ctx.db, _ids(ctx.body.get("ticket_ids")), ctx.body.get("status")
    )
    services.audit(
        ctx.db, user["id"], "tickets.status", f"{result['tickets']} tickets -> {result['status']}"
    )
    return 200, result


def bulk_note(ctx: Ctx):
    user = ctx.require_user()
    result = services.bulk_add_note(
        ctx.db,
        _ids(ctx.body.get("ticket_ids")),
        ctx.body.get("note"),
        mode="set" if ctx.body.get("mode") == "set" else "append",
    )
    services.audit(ctx.db, user["id"], "tickets.note", f"{result['tickets']} tickets")
    return 200, result


# ---------------------------------------------------------------- settings
def settings_get(ctx: Ctx):
    ctx.require_admin()
    return 200, {
        "retention_years": services.get_retention_years(ctx.db),
    }


def settings_update(ctx: Ctx):
    ctx.require_admin()
    if "retention_years" in ctx.body:
        try:
            years = max(1, int(ctx.body["retention_years"]))
        except (TypeError, ValueError):
            raise ApiError("Retention must be a number of years", 400)
        services.set_setting(ctx.db, "retention_years", str(years))
    services.audit(
        ctx.db, ctx.user["id"], "settings.update", f"retention_years={services.get_retention_years(ctx.db)}"
    )
    return 200, {"retention_years": services.get_retention_years(ctx.db)}


def settings_purge(ctx: Ctx):
    ctx.require_admin()
    result = services.purge_old_data(ctx.db)
    services.audit(
        ctx.db,
        ctx.user["id"],
        "settings.purge",
        f"{result['removed_tickets']} tickets removed (cutoff {result['cutoff']})",
    )
    return 200, result


# ---------------------------------------------------------------- misc
def stats(ctx: Ctx):
    ctx.require_user()
    return 200, services.day_stats(ctx.db, ctx.query.get("date") or services.today_iso())


def audit_list(ctx: Ctx):
    ctx.require_user()
    return 200, {"entries": services.list_audit(ctx.db, limit=200)}


def export_csv(ctx: Ctx):
    ctx.require_user()
    today = date.today()
    csv_text = services.export_tickets_csv(
        ctx.db,
        date_from=ctx.query.get("date_from") or today.isoformat(),
        date_to=ctx.query.get("date_to") or today.isoformat(),
        building_id=_int(ctx.query["building_id"]) if ctx.query.get("building_id") else None,
    )
    return 200, {
        "_raw": csv_text.encode("utf-8-sig"),
        "_content_type": "text/csv; charset=utf-8",
        "_download": f"tickets-{ctx.query.get('date_from') or today}-to-{ctx.query.get('date_to') or today}.csv",
    }


# ---------------------------------------------------------------- users
def users_list(ctx: Ctx):
    ctx.require_admin()
    return 200, {"users": auth.list_users(ctx.db)}


def users_create(ctx: Ctx):
    ctx.require_admin()
    user_id = auth.create_user(
        ctx.db,
        _str(ctx.body.get("username"), "Username", allow_empty=False),
        str(ctx.body.get("password") or ""),
        _str(ctx.body.get("display_name")),
        "admin" if ctx.body.get("role") == "admin" else "staff",
    )
    services.audit(ctx.db, ctx.user["id"], "user.create", ctx.body.get("username", ""))
    return 201, {"id": user_id}


def users_delete(ctx: Ctx):
    ctx.require_admin()
    auth.delete_user(ctx.db, _int(ctx.params["id"]))
    return 200, {"ok": True}


def users_password(ctx: Ctx):
    user = ctx.require_admin()
    target = _int(ctx.params["id"])
    if target != user["id"]:
        raise ApiError("You can only change your own password here", 403)
    auth.set_password(ctx.db, target, str(ctx.body.get("password") or ""))
    return 200, {"ok": True}


# ---------------------------------------------------------------- routing
Handler = Callable[[Ctx], tuple[int, Any]]

ROUTES: list[tuple[str, re.Pattern, Handler]] = []


def route(method: str, pattern: str):
    def register(handler: Handler):
        ROUTES.append((method, re.compile("^" + pattern + "$"), handler))
        return handler

    return register


route("GET", r"/api/health")(lambda ctx: (200, {"ok": True, "version": "1.0.0"}))
route("GET", r"/api/auth/status")(auth_status)
route("POST", r"/api/auth/setup")(auth_setup)
route("POST", r"/api/auth/login")(auth_login)
route("POST", r"/api/auth/logout")(auth_logout)
route("GET", r"/api/auth/me")(auth_me)
route("GET", r"/api/bootstrap")(bootstrap)

route("GET", r"/api/buildings")(buildings_list)
route("POST", r"/api/buildings")(buildings_create)
route("PATCH", r"/api/buildings/(?P<id>\d+)")(buildings_update)
route("DELETE", r"/api/buildings/(?P<id>\d+)")(buildings_delete)

route("GET", r"/api/residents")(residents_list)
route("POST", r"/api/residents")(residents_create)
route("GET", r"/api/residents/(?P<id>\d+)")(residents_get)
route("PATCH", r"/api/residents/(?P<id>\d+)")(residents_update)
route("DELETE", r"/api/residents/(?P<id>\d+)")(residents_delete)

route("GET", r"/api/items")(items_list)
route("POST", r"/api/items")(items_create)
route("PATCH", r"/api/items/(?P<id>\d+)")(items_update)
route("DELETE", r"/api/items/(?P<id>\d+)")(items_delete)

route("GET", r"/api/tickets")(tickets_list)
route("POST", r"/api/tickets")(tickets_create)
route("POST", r"/api/tickets/generate")(tickets_generate)
route("GET", r"/api/tickets/(?P<id>\d+)")(tickets_get)
route("PATCH", r"/api/tickets/(?P<id>\d+)")(tickets_update)
route("DELETE", r"/api/tickets/(?P<id>\d+)")(tickets_delete)
route("POST", r"/api/tickets/(?P<id>\d+)/items")(tickets_add_item)
route("PATCH", r"/api/tickets/(?P<id>\d+)/items/(?P<item_id>\d+)")(tickets_set_item)
route("DELETE", r"/api/tickets/(?P<id>\d+)/items/(?P<item_id>\d+)")(tickets_remove_item)

route("POST", r"/api/bulk/add")(bulk_add)
route("POST", r"/api/bulk/remove")(bulk_remove)
route("POST", r"/api/bulk/replace")(bulk_replace)
route("POST", r"/api/bulk/status")(bulk_status)
route("POST", r"/api/bulk/note")(bulk_note)

route("GET", r"/api/stats")(stats)
route("GET", r"/api/audit")(audit_list)
route("GET", r"/api/export.csv")(export_csv)

route("GET", r"/api/settings")(settings_get)
route("POST", r"/api/settings")(settings_update)
route("POST", r"/api/settings/purge")(settings_purge)

route("GET", r"/api/users")(users_list)
route("POST", r"/api/users")(users_create)
route("DELETE", r"/api/users/(?P<id>\d+)")(users_delete)
route("POST", r"/api/users/(?P<id>\d+)/password")(users_password)

PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login"}


def dispatch(
    db: Database,
    method: str,
    path: str,
    query: dict,
    body: dict | None,
    user: dict | None,
    token: str | None,
    client_ip: str,
) -> tuple[int, Any, list[tuple[str, str]], Ctx]:
    if method == "OPTIONS":
        return 204, None, [], Ctx(db, method, path, query, {}, user, token, client_ip)

    match = None
    allowed: set[str] = set()
    for route_method, pattern, handler in ROUTES:
        found = pattern.match(path)
        if not found:
            continue
        allowed.add(route_method)
        if route_method == method:
            match = (handler, found.groupdict())
            break

    ctx = Ctx(db, method, path, query, body or {}, user, token, client_ip)
    if not match:
        if allowed:
            return 405, {"error": "Method not allowed"}, [], ctx
        raise ApiError("Not found", 404)

    if path not in PUBLIC_PATHS and not user:
        raise ApiError("Please sign in", 401)

    handler, params = match
    ctx.params = params  # type: ignore[attr-defined]
    status, payload = handler(ctx)
    headers = list(ctx.headers)
    return status, payload, headers, ctx
