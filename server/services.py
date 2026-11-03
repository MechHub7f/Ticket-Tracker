"""Business logic for Ticket Tracker.

Everything that touches tickets, residents, menu items and the bulk actions
lives here so it can be unit tested without starting the web server.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any, Iterable

from .db import Database

MEALS = ["breakfast", "lunch", "dinner", "snack"]
MEAL_LABELS = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snack": "Snack",
}
STATUSES = ["open", "ready", "delivered", "cancelled"]
STATUS_LABELS = {
    "open": "Open",
    "ready": "Ready",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_iso() -> str:
    return date_cls.today().isoformat()


# ---------------------------------------------------------------------------
# Settings + compliance (consent tracking, data retention, purge)
# ---------------------------------------------------------------------------

DEFAULT_RETENTION_YEARS = 7


def get_setting(db: Database, key: str, default: str = "") -> str:
    row = db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(db: Database, key: str, value: str) -> None:
    if db.query_one("SELECT key FROM settings WHERE key = ?", (key,)):
        db.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    else:
        db.insert("settings", {"key": key, "value": value})


def get_retention_years(db: Database) -> int:
    try:
        return max(1, int(get_setting(db, "retention_years", str(DEFAULT_RETENTION_YEARS))))
    except ValueError:
        return DEFAULT_RETENTION_YEARS


def purge_old_data(db: Database, years: int | None = None) -> dict:
    """Remove tickets (and their items) for INACTIVE residents older than the
    retention window.  Active residents' records are never purged."""
    years = years or get_retention_years(db)
    cutoff = (date_cls.today() - timedelta(days=int(years) * 365)).isoformat()
    tickets = db.query(
        """SELECT t.id FROM tickets t
           JOIN residents r ON r.id = t.resident_id
           WHERE t.service_date < ? AND r.active = 0""",
        (cutoff,),
    )
    ticket_ids = [t["id"] for t in tickets]
    removed_items = 0
    if ticket_ids:
        placeholders = ",".join("?" for _ in ticket_ids)
        removed_items = db.execute(
            f"DELETE FROM ticket_items WHERE ticket_id IN ({placeholders})",
            tuple(ticket_ids),
        )
    removed_tickets = db.execute(
        """DELETE FROM tickets WHERE service_date < ?
           AND resident_id IN (SELECT id FROM residents WHERE active = 0)""",
        (cutoff,),
    )
    return {
        "cutoff": cutoff,
        "years": years,
        "removed_tickets": removed_tickets,
        "removed_items": removed_items,
    }


def _check_date(value: str) -> str:
    try:
        return date_cls.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError("Date must be in YYYY-MM-DD format")


def _check_meal(value: str) -> str:
    value = (value or "").strip().lower()
    if value not in MEALS:
        raise ValueError(f"Meal must be one of: {', '.join(MEALS)}")
    return value


def _check_status(value: str) -> str:
    value = (value or "").strip().lower()
    if value not in STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(STATUSES)}")
    return value


def _clean_text(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


# --------------------------------------------------------------------------
# Allergy / diet warnings
# --------------------------------------------------------------------------
ALLERGEN_PHRASES = {
    "peanuts": ["peanut", "peanuts"],
    "tree nuts": ["tree nut", "tree nuts", "nuts", "nut"],
    "dairy": ["dairy", "milk", "lactose"],
    "egg": ["egg", "eggs"],
    "fish": ["fish"],
    "shellfish": ["shellfish", "shrimp", "prawn", "crab", "lobster"],
    "soy": ["soy", "soya"],
    "gluten": ["gluten", "wheat", "celiac", "coeliac"],
    "sesame": ["sesame"],
    "mustard": ["mustard"],
    "celery": ["celery"],
    "sulfites": ["sulfite", "sulfites", "sulphite", "sulphites"],
}

DIET_RULES = [
    {
        "label": "Gluten-free diet",
        "phrases": ["gluten free", "gluten-free", "celiac", "coeliac", "no gluten"],
        "avoid": ["gluten"],
        "ok_tags": ["gluten free"],
        "detail": "item may contain gluten",
    },
    {
        "label": "Dairy-free diet",
        "phrases": ["dairy free", "dairy-free", "no dairy", "lactose free", "lactose-free"],
        "avoid": ["dairy"],
        "ok_tags": ["dairy free"],
        "detail": "item may contain dairy",
    },
    {
        "label": "Nut-free diet",
        "phrases": ["nut free", "nut-free", "no nuts"],
        "avoid": ["peanuts", "tree nuts"],
        "ok_tags": ["nut free"],
        "detail": "item may contain nuts",
    },
    {
        "label": "Vegetarian diet",
        "phrases": ["vegetarian", "no meat"],
        "avoid": ["meat", "poultry", "fish", "shellfish"],
        "ok_tags": ["vegetarian", "vegan"],
        "detail": "item contains meat or fish",
    },
    {
        "label": "Vegan diet",
        "phrases": ["vegan", "plant based", "plant-based"],
        "avoid": ["meat", "poultry", "fish", "shellfish", "dairy", "egg", "honey"],
        "ok_tags": ["vegan"],
        "detail": "item contains an animal product",
    },
    {
        "label": "Low-sodium diet",
        "phrases": ["low sodium", "low-sodium", "low salt", "no salt", "renal"],
        "avoid": [],
        "avoid_tags": ["high sodium", "high-sodium"],
        "ok_tags": ["low sodium", "low-sodium"],
        "detail": "item is high in sodium",
    },
    {
        "label": "Diabetic / low-sugar diet",
        "phrases": ["diabetic", "low sugar", "low-sugar", "no sugar", "no added sugar"],
        "avoid": [],
        "avoid_tags": ["high sugar", "high-sugar"],
        "ok_tags": ["diabetic friendly", "sugar free", "no added sugar"],
        "detail": "item is high in sugar",
    },
    {
        "label": "Pureed texture",
        "phrases": ["pureed", "puree", "purée"],
        "avoid": [],
        "avoid_tags": ["texture:regular", "texture:minced"],
        "ok_tags": ["texture:pureed", "pureed"],
        "detail": "item does not match a pureed texture",
    },
    {
        "label": "Low-potassium diet",
        "phrases": ["low potassium", "low-potassium"],
        "avoid": [],
        "avoid_tags": ["high potassium", "high-potassium"],
        "ok_tags": ["low potassium", "low-potassium"],
        "detail": "item is high in potassium",
    },
]


def _normalise(text: Any) -> str:
    text = str(text or "").lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def _has_phrase(haystack: str, phrase: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", haystack))


def _split_tags(raw: str) -> list[str]:
    return [t.strip() for t in str(raw or "").split(",") if t.strip()]


def item_facts(item: dict) -> tuple[set[str], set[str]]:
    """Return (allergens, tags) for a menu item, both normalised."""
    tags = {_normalise(t) for t in _split_tags(item.get("tags", ""))}
    allergens = set()
    for tag in tags:
        if tag.startswith("contains "):
            allergens.add(tag[len("contains "):].strip())
        elif tag.startswith("contains:"):
            allergens.add(tag[len("contains:"):].strip())
    return allergens, tags


def item_allergens(item: dict) -> list[str]:
    return sorted(item_facts(item)[0])


def conflict_check(resident: dict, item: dict) -> list[dict]:
    """Return warnings when an item clashes with a resident's allergies/diet."""
    warnings: list[dict] = []
    allergy_text = _normalise(resident.get("allergies", ""))
    diet_text = _normalise(resident.get("diet", ""))
    allergens, tags = item_facts(item)

    if allergy_text:
        padded = f" {allergy_text} "
        for allergen in sorted(allergens):
            phrases = ALLERGEN_PHRASES.get(allergen, [allergen])
            for phrase in phrases:
                if f" {phrase} " in padded or _has_phrase(allergy_text, phrase):
                    warnings.append(
                        {
                            "type": "allergy",
                            "label": f"Allergy: {allergen}",
                            "detail": f"{resident.get('name', 'Resident')} is allergic to "
                            f"{allergen} and this item contains it.",
                        }
                    )
                    break

    for rule in DIET_RULES:
        if not any(_has_phrase(diet_text, _normalise(p)) for p in rule["phrases"]):
            continue
        if any(tag in tags for tag in rule.get("ok_tags", [])):
            continue
        hit = any(a in allergens for a in rule.get("avoid", []))
        if not hit:
            hit = any(_normalise(t) in tags for t in rule.get("avoid_tags", []))
        if hit:
            warnings.append(
                {
                    "type": "diet",
                    "label": rule["label"],
                    "detail": f"{resident.get('name', 'Resident')}: {rule['detail']}.",
                }
            )

    # De-duplicate by label
    seen = set()
    unique = []
    for warning in warnings:
        key = (warning["type"], warning["label"])
        if key not in seen:
            seen.add(key)
            unique.append(warning)
    return unique


# --------------------------------------------------------------------------
# Buildings
# --------------------------------------------------------------------------
def list_buildings(db: Database) -> list[dict]:
    return db.query(
        """
        SELECT b.id, b.name, b.notes,
               (SELECT COUNT(*) FROM residents r
                 WHERE r.building_id = b.id AND r.active = 1) AS resident_count
        FROM buildings b
        ORDER BY LOWER(b.name)
        """
    )


def create_building(db: Database, data: dict) -> dict:
    name = _clean_text(data.get("name"), 120)
    if not name:
        raise ValueError("Building name is required")
    new_id = db.insert(
        "buildings", {"name": name, "notes": _clean_text(data.get("notes"))}
    )
    return {"id": new_id, "name": name}


def update_building(db: Database, building_id: int, data: dict) -> None:
    fields = {}
    if "name" in data:
        name = _clean_text(data["name"], 120)
        if not name:
            raise ValueError("Building name is required")
        fields["name"] = name
    if "notes" in data:
        fields["notes"] = _clean_text(data["notes"])
    if fields:
        db.update("buildings", building_id, fields)


def delete_building(db: Database, building_id: int) -> None:
    db.delete("buildings", building_id)


# --------------------------------------------------------------------------
# Residents
# --------------------------------------------------------------------------
RESIDENT_FIELDS = ("name", "building_id", "room", "allergies", "diet", "notes", "active")


def _resident_row(data: dict, partial: bool = False) -> dict:
    fields: dict[str, Any] = {}
    for key in RESIDENT_FIELDS:
        if key not in data:
            continue
        if key == "name":
            name = _clean_text(data[key], 160)
            if not name:
                raise ValueError("Resident name is required")
            fields[key] = name
        elif key == "building_id":
            value = data[key]
            fields[key] = int(value) if value not in (None, "", "null") else None
        elif key == "active":
            fields[key] = 1 if data[key] in (True, 1, "1", "true", "on") else 0
        else:
            fields[key] = _clean_text(data[key])
    if not partial and "name" not in fields:
        raise ValueError("Resident name is required")
    return fields


def list_residents(
    db: Database,
    q: str = "",
    building_id: int | None = None,
    active: int | None = 1,
) -> list[dict]:
    sql = """
        SELECT r.*, b.name AS building_name
        FROM residents r
        LEFT JOIN buildings b ON b.id = r.building_id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if q:
        sql += " AND (LOWER(r.name) LIKE ? OR LOWER(r.room) LIKE ? OR LOWER(r.allergies) LIKE ? OR LOWER(r.diet) LIKE ?)"
        needle = f"%{q.lower()}%"
        params += [needle, needle, needle, needle]
    if building_id:
        sql += " AND r.building_id = ?"
        params.append(building_id)
    if active is not None:
        sql += " AND r.active = ?"
        params.append(active)
    sql += " ORDER BY LOWER(r.name)"
    return db.query(sql, params)


def get_resident(db: Database, resident_id: int) -> dict | None:
    return db.query_one(
        """
        SELECT r.*, b.name AS building_name
        FROM residents r LEFT JOIN buildings b ON b.id = r.building_id
        WHERE r.id = ?
        """,
        (resident_id,),
    )


def _consent_guard(fields: dict, existing: dict | None) -> None:
    """NH compliance: a consent date must be on file before medical info
    (allergies / diet restrictions) is recorded or changed."""
    consent = fields.get("consent_date", None)
    if existing is not None:
        consent = consent if consent is not None else existing.get("consent_date", "")
    allergies = fields.get("allergies", None)
    diet = fields.get("diet", None)
    if existing is not None:
        allergies = allergies if allergies is not None else existing.get("allergies", "")
        diet = diet if diet is not None else existing.get("diet", "")
    has_medical = bool((allergies or "").strip() or (diet or "").strip())
    if has_medical and not (consent or "").strip():
        raise ValueError(
            "A consent date is required before allergies or diet restrictions can be recorded"
        )


def create_resident(db: Database, data: dict) -> int:
    fields = _resident_row(data)
    if data.get("consent_date"):
        fields["consent_date"] = _check_date(data["consent_date"])
    _consent_guard(fields, None)
    timestamp = now_iso()
    fields.setdefault("active", 1)
    fields["created_at"] = timestamp
    fields["updated_at"] = timestamp
    return db.insert("residents", fields)


def update_resident(db: Database, resident_id: int, data: dict) -> None:
    existing = db.query_one("SELECT * FROM residents WHERE id = ?", (resident_id,))
    if not existing:
        raise ValueError("Resident not found")
    fields = _resident_row(data, partial=True)
    if data.get("consent_date"):
        fields["consent_date"] = _check_date(data["consent_date"])
    _consent_guard(fields, existing)
    if not fields:
        return
    fields["updated_at"] = now_iso()
    db.update("residents", resident_id, fields)


def delete_resident(db: Database, resident_id: int) -> None:
    db.delete("residents", resident_id)


# --------------------------------------------------------------------------
# Menu items
# --------------------------------------------------------------------------
def list_items(db: Database, q: str = "", category: str = "", active: int | None = 1) -> list[dict]:
    sql = "SELECT * FROM meal_items WHERE 1 = 1"
    params: list[Any] = []
    if q:
        sql += " AND (LOWER(name) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(category) LIKE ?)"
        needle = f"%{q.lower()}%"
        params += [needle, needle, needle]
    if category:
        sql += " AND category = ?"
        params.append(category)
    if active is not None:
        sql += " AND active = ?"
        params.append(active)
    sql += " ORDER BY LOWER(category), LOWER(name)"
    items = db.query(sql, params)
    for item in items:
        item["allergens"] = item_allergens(item)
    return items


def get_item(db: Database, item_id: int) -> dict | None:
    item = db.query_one("SELECT * FROM meal_items WHERE id = ?", (item_id,))
    if item:
        item["allergens"] = item_allergens(item)
    return item


def create_item(db: Database, data: dict) -> int:
    name = _clean_text(data.get("name"), 160)
    if not name:
        raise ValueError("Item name is required")
    timestamp = now_iso()
    return db.insert(
        "meal_items",
        {
            "name": name,
            "category": _clean_text(data.get("category") or "Other", 60),
            "tags": ", ".join(_split_tags(data.get("tags", ""))),
            "notes": _clean_text(data.get("notes")),
            "active": 1 if data.get("active", 1) in (True, 1, "1", "true", "on") else 0,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )


def update_item(db: Database, item_id: int, data: dict) -> None:
    fields: dict[str, Any] = {}
    for key in ("name", "category", "notes"):
        if key in data:
            value = _clean_text(data[key], 160)
            if key == "name" and not value:
                raise ValueError("Item name is required")
            fields[key] = value
    if "tags" in data:
        fields["tags"] = ", ".join(_split_tags(data["tags"]))
    if "active" in data:
        fields["active"] = 1 if data["active"] in (True, 1, "1", "true", "on") else 0
    if not fields:
        return
    fields["updated_at"] = now_iso()
    db.update("meal_items", item_id, fields)


def delete_item(db: Database, item_id: int) -> None:
    db.delete("meal_items", item_id)


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------
def list_tickets(
    db: Database,
    service_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    meal: str | None = None,
    building_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    resident_id: int | None = None,
    ids: Iterable[int] | None = None,
    active_only: bool = False,
    limit: int = 5000,
) -> list[dict]:
    sql = """
        SELECT t.id, t.resident_id, t.service_date, t.meal, t.status, t.notes,
               t.created_at, t.updated_at,
               r.name AS resident_name, r.room, r.allergies, r.diet,
               r.notes AS resident_notes, r.building_id,
               b.name AS building_name
        FROM tickets t
        JOIN residents r ON r.id = t.resident_id
        LEFT JOIN buildings b ON b.id = r.building_id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if active_only:
        sql += " AND r.active = 1"
    if service_date:
        sql += " AND t.service_date = ?"
        params.append(_check_date(service_date))
    if date_from:
        sql += " AND t.service_date >= ?"
        params.append(_check_date(date_from))
    if date_to:
        sql += " AND t.service_date <= ?"
        params.append(_check_date(date_to))
    if meal:
        sql += " AND t.meal = ?"
        params.append(_check_meal(meal))
    if building_id:
        sql += " AND r.building_id = ?"
        params.append(int(building_id))
    if status:
        sql += " AND t.status = ?"
        params.append(_check_status(status))
    if resident_id:
        sql += " AND t.resident_id = ?"
        params.append(int(resident_id))
    if q:
        sql += " AND (LOWER(r.name) LIKE ? OR LOWER(r.room) LIKE ? OR LOWER(COALESCE(t.notes, '')) LIKE ? OR LOWER(r.allergies) LIKE ? OR LOWER(r.diet) LIKE ?)"
        needle = f"%{q.lower()}%"
        params += [needle, needle, needle, needle, needle]
    if ids is not None:
        id_list = [int(i) for i in ids]
        if not id_list:
            return []
        sql += f" AND t.id IN ({', '.join('?' for _ in id_list)})"
        params += id_list
    sql += " ORDER BY LOWER(b.name), LOWER(r.name), t.meal LIMIT ?"
    params.append(int(limit))

    tickets = db.query(sql, params)
    if not tickets:
        return []

    ticket_ids = [t["id"] for t in tickets]
    items_by_ticket: dict[int, list[dict]] = {}
    for chunk in _chunks(ticket_ids, 400):
        rows = db.query(
            f"""
            SELECT ti.id, ti.ticket_id, ti.item_id, ti.qty, ti.note,
                   mi.name, mi.category, mi.tags
            FROM ticket_items ti
            JOIN meal_items mi ON mi.id = ti.item_id
            WHERE ti.ticket_id IN ({', '.join('?' for _ in chunk)})
            ORDER BY LOWER(mi.category), LOWER(mi.name)
            """,
            chunk,
        )
        for row in rows:
            items_by_ticket.setdefault(row["ticket_id"], []).append(row)
    for ticket in tickets:
        ticket["date"] = ticket["service_date"]
        ticket["meal_label"] = MEAL_LABELS.get(ticket["meal"], ticket["meal"])
        ticket["status_label"] = STATUS_LABELS.get(ticket["status"], ticket["status"])
        ticket["items"] = items_by_ticket.get(ticket["id"], [])
        ticket["item_count"] = sum(i["qty"] for i in ticket["items"])
    return tickets


def _chunks(seq: list, size: int) -> Iterable[list]:
    for start in range(0, len(seq), size):
        yield seq[start : start + size]


def get_ticket(db: Database, ticket_id: int) -> dict | None:
    rows = list_tickets(db, ids=[ticket_id])
    return rows[0] if rows else None


def create_ticket(db: Database, data: dict) -> int:
    resident_id = int(data.get("resident_id") or 0)
    if not resident_id or not get_resident(db, resident_id):
        raise ValueError("A valid resident is required")
    service_date = _check_date(data.get("date") or today_iso())
    meal = _check_meal(data.get("meal"))
    timestamp = now_iso()
    existing = db.query_one(
        "SELECT id FROM tickets WHERE resident_id = ? AND service_date = ? AND meal = ?",
        (resident_id, service_date, meal),
    )
    if existing:
        return int(existing["id"])
    return db.insert(
        "tickets",
        {
            "resident_id": resident_id,
            "service_date": service_date,
            "meal": meal,
            "status": "open",
            "notes": _clean_text(data.get("notes")),
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )


def update_ticket(db: Database, ticket_id: int, data: dict) -> None:
    fields: dict[str, Any] = {}
    if "status" in data:
        fields["status"] = _check_status(data["status"])
    if "notes" in data:
        fields["notes"] = _clean_text(data["notes"])
    if "meal" in data:
        fields["meal"] = _check_meal(data["meal"])
    if "date" in data:
        fields["service_date"] = _check_date(data["date"])
    if not fields:
        return
    fields["updated_at"] = now_iso()
    db.update("tickets", ticket_id, fields)


def delete_ticket(db: Database, ticket_id: int) -> None:
    db.delete("tickets", ticket_id)


# --------------------------------------------------------------------------
# Single-ticket item operations
# --------------------------------------------------------------------------
def add_item_to_ticket(db: Database, ticket_id: int, item_id: int, qty: int = 1) -> list[dict]:
    qty = max(1, int(qty or 1))
    ticket = get_ticket(db, ticket_id)
    item = get_item(db, item_id)
    if not ticket or not item:
        raise ValueError("Ticket or item not found")
    db.execute(
        """
        INSERT INTO ticket_items (ticket_id, item_id, qty, note)
        VALUES (?, ?, ?, '')
        ON CONFLICT (ticket_id, item_id) DO UPDATE SET qty = qty + excluded.qty
        """,
        (ticket_id, item_id, qty),
    )
    return conflict_check(ticket, item)


def set_ticket_item(db: Database, ticket_id: int, item_id: int, qty: int) -> None:
    if int(qty) <= 0:
        remove_item_from_ticket(db, ticket_id, item_id)
        return
    db.update(
        "ticket_items",
        _ticket_item_id(db, ticket_id, item_id),
        {"qty": int(qty)},
    )


def remove_item_from_ticket(db: Database, ticket_id: int, item_id: int) -> None:
    db.execute(
        "DELETE FROM ticket_items WHERE ticket_id = ? AND item_id = ?",
        (ticket_id, item_id),
    )


def _ticket_item_id(db: Database, ticket_id: int, item_id: int) -> int:
    row = db.query_one(
        "SELECT id FROM ticket_items WHERE ticket_id = ? AND item_id = ?",
        (ticket_id, item_id),
    )
    if not row:
        raise ValueError("That item is not on the ticket")
    return int(row["id"])


# --------------------------------------------------------------------------
# Bulk operations - the heart of the app
# --------------------------------------------------------------------------
def _load_bulk_context(db: Database, ticket_ids: Iterable[int], item_ids: Iterable[int]):
    ticket_ids = sorted({int(t) for t in ticket_ids or []})
    item_ids = sorted({int(i) for i in item_ids or []})
    if not ticket_ids:
        raise ValueError("Select at least one ticket")
    if not item_ids:
        raise ValueError("Select at least one meal item")
    tickets = list_tickets(db, ids=ticket_ids)
    if not tickets:
        raise ValueError("No matching tickets found")
    items = [get_item(db, item_id) for item_id in item_ids]
    items = [i for i in items if i]
    if not items:
        raise ValueError("No matching menu items found")
    return tickets, items


def bulk_add_items(
    db: Database,
    ticket_ids: Iterable[int],
    item_ids: Iterable[int],
    qty: int = 1,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    tickets, items = _load_bulk_context(db, ticket_ids, item_ids)
    qty = max(1, int(qty or 1))

    conflicts = []
    for ticket in tickets:
        for item in items:
            for warning in conflict_check(ticket, item):
                conflicts.append(
                    {
                        "ticket_id": ticket["id"],
                        "resident_id": ticket["resident_id"],
                        "resident_name": ticket["resident_name"],
                        "item_id": item["id"],
                        "item_name": item["name"],
                        "ticket": ticket["id"],
                        "resident": ticket["resident_name"],
                        "reason": f"{warning['label']} - {warning['detail']}",
                        **warning,
                    }
                )

    result = {
        "tickets": len(tickets),
        "items": len(items),
        "qty": qty,
        "conflicts": conflicts,
        "requires_confirmation": bool(conflicts) and not force,
        "applied": False,
    }
    if dry_run or (conflicts and not force):
        return result

    rows = [
        (ticket["id"], item["id"], qty)
        for ticket in tickets
        for item in items
    ]
    db.executemany(
        """
        INSERT INTO ticket_items (ticket_id, item_id, qty, note)
        VALUES (?, ?, ?, '')
        ON CONFLICT (ticket_id, item_id) DO UPDATE SET qty = qty + excluded.qty
        """,
        rows,
    )
    result["applied"] = True
    result["ticket_ids"] = [t["id"] for t in tickets]
    return result


def bulk_remove_items(
    db: Database,
    ticket_ids: Iterable[int],
    item_ids: Iterable[int],
    qty: int | None = None,
    remove_all: bool = False,
) -> dict:
    ticket_ids = sorted({int(t) for t in ticket_ids or []})
    item_ids = sorted({int(i) for i in item_ids or []})
    if not ticket_ids:
        raise ValueError("Select at least one ticket")
    if not item_ids:
        raise ValueError("Select at least one meal item")

    placeholders = ", ".join("?" for _ in ticket_ids)
    item_placeholders = ", ".join("?" for _ in item_ids)
    existing = db.query(
        f"""
        SELECT COUNT(*) AS n FROM ticket_items
        WHERE ticket_id IN ({placeholders}) AND item_id IN ({item_placeholders})
        """,
        ticket_ids + item_ids,
    )

    if remove_all or qty is None:
        db.execute(
            f"DELETE FROM ticket_items WHERE ticket_id IN ({placeholders}) AND item_id IN ({item_placeholders})",
            ticket_ids + item_ids,
        )
        removed_rows = existing[0]["n"] if existing else 0
    else:
        qty = max(1, int(qty))
        db.execute(
            f"""UPDATE ticket_items SET qty = qty - ?
                WHERE ticket_id IN ({placeholders}) AND item_id IN ({item_placeholders})""",
            [qty] + ticket_ids + item_ids,
        )
        db.execute(
            f"DELETE FROM ticket_items WHERE qty <= 0 AND ticket_id IN ({placeholders}) AND item_id IN ({item_placeholders})",
            ticket_ids + item_ids,
        )
        removed_rows = 0

    return {
        "tickets": len(ticket_ids),
        "items": len(item_ids),
        "removed_rows": removed_rows,
        "applied": True,
        "ticket_ids": ticket_ids,
    }


def bulk_replace_item(
    db: Database,
    ticket_ids: Iterable[int],
    from_item_id: int,
    to_item_id: int,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    if int(from_item_id) == int(to_item_id):
        raise ValueError("Choose two different items")
    tickets, _ = _load_bulk_context(
        db, ticket_ids, [from_item_id, to_item_id]
    )
    from_item = get_item(db, from_item_id)
    to_item = get_item(db, to_item_id)
    if not from_item or not to_item:
        raise ValueError("Item not found")

    affected = [t for t in tickets if any(i["item_id"] == from_item_id for i in t["items"])]
    conflicts = []
    for ticket in affected:
        for warning in conflict_check(ticket, to_item):
            conflicts.append(
                {
                    "ticket_id": ticket["id"],
                    "resident_id": ticket["resident_id"],
                    "resident_name": ticket["resident_name"],
                    "item_id": to_item["id"],
                    "item_name": to_item["name"],
                    "ticket": ticket["id"],
                    "resident": ticket["resident_name"],
                    "reason": f"{warning['label']} - {warning['detail']}",
                    **warning,
                }
            )

    result = {
        "tickets": len(affected),
        "from_item": from_item["name"],
        "to_item": to_item["name"],
        "conflicts": conflicts,
        "requires_confirmation": bool(conflicts) and not force,
        "applied": False,
    }
    if dry_run or (conflicts and not force):
        return result

    for ticket in affected:
        current = next(i for i in ticket["items"] if i["item_id"] == from_item_id)
        existing_target = next(
            (i for i in ticket["items"] if i["item_id"] == to_item_id), None
        )
        if existing_target:
            db.execute(
                "UPDATE ticket_items SET qty = qty + ? WHERE id = ?",
                (current["qty"], existing_target["id"]),
            )
            db.execute("DELETE FROM ticket_items WHERE id = ?", (current["id"],))
        else:
            db.execute(
                "UPDATE ticket_items SET item_id = ? WHERE id = ?",
                (to_item_id, current["id"]),
            )
    result["applied"] = True
    result["ticket_ids"] = [t["id"] for t in affected]
    return result


def bulk_set_status(db: Database, ticket_ids: Iterable[int], status: str) -> dict:
    ticket_ids = sorted({int(t) for t in ticket_ids or []})
    if not ticket_ids:
        raise ValueError("Select at least one ticket")
    status = _check_status(status)
    placeholders = ", ".join("?" for _ in ticket_ids)
    db.execute(
        f"UPDATE tickets SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
        [status, now_iso()] + ticket_ids,
    )
    return {"tickets": len(ticket_ids), "status": status}


def bulk_add_note(db: Database, ticket_ids: Iterable[int], note: str, mode: str = "append") -> dict:
    ticket_ids = sorted({int(t) for t in ticket_ids or []})
    if not ticket_ids:
        raise ValueError("Select at least one ticket")
    note = _clean_text(note)
    if not note:
        raise ValueError("Note cannot be empty")
    timestamp = now_iso()
    if mode == "set":
        placeholders = ", ".join("?" for _ in ticket_ids)
        db.execute(
            f"UPDATE tickets SET notes = ?, updated_at = ? WHERE id IN ({placeholders})",
            [note, timestamp] + ticket_ids,
        )
    else:
        for ticket_id in ticket_ids:
            row = db.query_one("SELECT notes FROM tickets WHERE id = ?", (ticket_id,))
            if not row:
                continue
            current = (row.get("notes") or "").strip()
            merged = f"{current}\n{note}".strip() if current else note
            db.execute(
                "UPDATE tickets SET notes = ?, updated_at = ? WHERE id = ?",
                (merged[:4000], timestamp, ticket_id),
            )
    return {"tickets": len(ticket_ids), "note": note, "mode": mode}


def generate_tickets(
    db: Database,
    service_date: str,
    meals: Iterable[str] | None = None,
    building_ids: Iterable[int] | None = None,
    resident_ids: Iterable[int] | None = None,
) -> dict:
    service_date = _check_date(service_date or today_iso())
    meals = [_check_meal(m) for m in (meals or ["breakfast", "lunch", "dinner"])]
    building_ids = [int(b) for b in building_ids or [] if b]
    resident_ids = [int(r) for r in resident_ids or [] if r]

    residents = list_residents(db, active=1)
    if building_ids:
        residents = [r for r in residents if r["building_id"] in building_ids]
    if resident_ids:
        residents = [r for r in residents if r["id"] in resident_ids]
    if not residents:
        return {"created": 0, "skipped": 0, "date": service_date}

    resident_id_set = [r["id"] for r in residents]
    meal_placeholders = ", ".join("?" for _ in meals)
    rid_placeholders = ", ".join("?" for _ in resident_id_set)
    existing = db.query(
        f"""SELECT resident_id, meal FROM tickets
            WHERE service_date = ? AND meal IN ({meal_placeholders})
              AND resident_id IN ({rid_placeholders})""",
        [service_date] + meals + resident_id_set,
    )
    existing_set = {(row["resident_id"], row["meal"]) for row in existing}

    timestamp = now_iso()
    rows = []
    skipped = 0
    for resident in residents:
        for meal in meals:
            if (resident["id"], meal) in existing_set:
                skipped += 1
                continue
            rows.append((resident["id"], service_date, meal, "open", "", timestamp, timestamp))

    if rows:
        db.executemany(
            """INSERT INTO tickets
               (resident_id, service_date, meal, status, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return {
        "created": len(rows),
        "skipped": skipped,
        "date": service_date,
        "meals": meals,
        "residents": len(residents),
    }


# --------------------------------------------------------------------------
# Stats / export / audit
# --------------------------------------------------------------------------
def day_stats(db: Database, service_date: str) -> dict:
    service_date = _check_date(service_date or today_iso())
    rows = db.query(
        """SELECT status, COUNT(*) AS n FROM tickets
           WHERE service_date = ? GROUP BY status""",
        (service_date,),
    )
    counts = {row["status"]: row["n"] for row in rows}
    total = sum(counts.values())
    items = db.query_one(
        """SELECT COALESCE(SUM(ti.qty), 0) AS n
           FROM ticket_items ti JOIN tickets t ON t.id = ti.ticket_id
           WHERE t.service_date = ?""",
        (service_date,),
    )
    return {
        "date": service_date,
        "total": total,
        "by_status": {status: counts.get(status, 0) for status in STATUSES},
        "item_qty": int(items["n"]) if items else 0,
    }


def audit(db: Database, user_id: int | None, action: str, detail: str = "") -> None:
    db.insert(
        "audit_log",
        {
            "user_id": user_id,
            "action": action,
            "detail": _clean_text(detail, 800),
            "created_at": now_iso(),
        },
    )


def list_audit(db: Database, limit: int = 100) -> list[dict]:
    return db.query(
        """SELECT a.id, a.action, a.detail, a.created_at,
                  COALESCE(u.display_name, u.username, 'System') AS user_name
           FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
           ORDER BY a.id DESC LIMIT ?""",
        (int(limit),),
    )


def export_tickets_csv(
    db: Database,
    date_from: str,
    date_to: str,
    building_id: int | None = None,
) -> str:
    tickets = list_tickets(
        db,
        date_from=_check_date(date_from),
        date_to=_check_date(date_to),
        building_id=building_id,
        limit=100000,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Date",
            "Meal",
            "Resident",
            "Building",
            "Room",
            "Allergies",
            "Diet restrictions",
            "Items",
            "Status",
            "Ticket notes",
            "Resident notes",
        ]
    )
    for ticket in tickets:
        items = "; ".join(f"{i['qty']}x {i['name']}" for i in ticket["items"])
        writer.writerow(
            [
                ticket["service_date"],
                ticket["meal_label"],
                ticket["resident_name"],
                ticket["building_name"] or "",
                ticket["room"] or "",
                ticket["allergies"] or "",
                ticket["diet"] or "",
                items,
                ticket["status_label"],
                ticket["notes"] or "",
                ticket["resident_notes"] or "",
            ]
        )
    return buffer.getvalue()
