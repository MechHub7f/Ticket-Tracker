"""Demo data so a fresh install has something to look at."""

from __future__ import annotations

import random
from datetime import date, timedelta

from .db import Database
from .services import now_iso

BUILDINGS = [
    ("Maple House", "Assisted living - north wing"),
    ("Oak Court", "Memory care"),
    ("Willow Wing", "Independent living"),
    ("Cedar Lodge", "Skilled nursing"),
]

MENU_ITEMS = [
    ("Scrambled eggs", "Breakfast", "vegetarian, contains:egg, contains:dairy, low sodium"),
    ("Oatmeal", "Breakfast", "vegan, contains:gluten"),
    ("Gluten-free toast", "Breakfast", "vegetarian, gluten free"),
    ("Whole wheat toast", "Breakfast", "vegetarian, contains:gluten"),
    ("Turkey sausage", "Breakfast", "contains:meat, high sodium"),
    ("Bacon", "Breakfast", "contains:meat, high sodium"),
    ("Greek yogurt", "Breakfast", "vegetarian, contains:dairy"),
    ("Fresh fruit cup", "Breakfast", "vegan, gluten free"),
    ("Pancakes", "Breakfast", "vegetarian, contains:gluten, contains:dairy, high sugar"),
    ("Roast chicken", "Protein", "contains:meat, low sodium, gluten free"),
    ("Baked fish", "Protein", "contains:fish, gluten free"),
    ("Meatloaf", "Protein", "contains:meat, contains:gluten, high sodium"),
    ("Vegetable lasagna", "Protein", "vegetarian, contains:gluten, contains:dairy"),
    ("Mashed potatoes", "Starch", "vegetarian, contains:dairy"),
    ("Brown rice", "Starch", "vegan, gluten free, low sodium"),
    ("Gluten-free pasta", "Starch", "vegetarian, gluten free"),
    ("Mac and cheese", "Starch", "vegetarian, contains:gluten, contains:dairy, high sodium"),
    ("Steamed broccoli", "Vegetable", "vegan, gluten free, low sodium"),
    ("Green beans", "Vegetable", "vegan, gluten free, low sodium"),
    ("Garden salad", "Vegetable", "vegan, gluten free, low sodium"),
    ("Pureed carrots", "Vegetable", "vegan, gluten free, texture:pureed"),
    ("Apple slices", "Fruit", "vegan, gluten free"),
    ("Banana", "Fruit", "vegan, gluten free, low potassium"),
    ("Vanilla pudding", "Dessert", "vegetarian, contains:dairy, high sugar, texture:pureed"),
    ("Chocolate cake", "Dessert", "vegetarian, contains:gluten, contains:dairy, contains:egg, high sugar"),
    ("Sugar-free jello", "Dessert", "vegan, gluten free, diabetic friendly"),
    ("Peanut butter cookie", "Dessert", "vegetarian, contains:peanuts, contains:gluten, high sugar"),
    ("Milk", "Beverage", "vegetarian, contains:dairy"),
    ("Orange juice", "Beverage", "vegan, gluten free, high sugar"),
    ("Coffee", "Beverage", "vegan, gluten free"),
    ("Tea", "Beverage", "vegan, gluten free"),
    ("Tomato soup", "Soup", "vegetarian, contains:dairy, high sodium"),
    ("Chicken noodle soup", "Soup", "contains:meat, contains:gluten, high sodium"),
    ("Hummus with pita", "Snack", "vegan, contains:sesame, contains:gluten"),
]

RESIDENTS = [
    ("Eleanor Whitfield", 1, "101", "Penicillin", "Low sodium, diabetic", "Prefers tea with breakfast."),
    ("Harold Brennan", 1, "102", "", "Low sodium", "Likes extra napkins."),
    ("Margaret Okafor", 1, "103", "Shellfish", "Gluten-free", "Celiac - strict gluten-free."),
    ("Stanley Nowak", 1, "104", "Peanuts", "Nut-free", "Peanut allergy is severe."),
    ("Ruth Delgado", 1, "105", "", "Diabetic, low sugar", "No added sugar."),
    ("Franklin Holt", 1, "106", "Dairy", "Dairy-free", "Uses oat milk."),
    ("Virginia Marsh", 2, "201", "", "Pureed, low sodium", "Pureed textures only."),
    ("Arthur Bell", 2, "202", "Eggs", "Low sodium", "Egg allergy."),
    ("Lillian Tran", 2, "203", "", "Vegetarian", "Prefers small portions."),
    ("Walter Simmons", 2, "204", "Gluten", "Gluten-free", "Celiac - strict gluten-free."),
    ("Dorothy Ellis", 2, "205", "", "Diabetic, low sugar", "Check blood sugar before meals."),
    ("Samuel Reyes", 2, "206", "Fish, shellfish", "Low sodium", "Seafood allergy."),
    ("Betty Kowalski", 3, "301", "", "Low potassium, renal", "Renal diet - no bananas."),
    ("George Patel", 3, "302", "", "Low sodium", "Enjoys coffee."),
    ("Helen Branson", 3, "303", "Tree nuts", "Nut-free", "Tree nut allergy."),
    ("Robert Chen", 3, "304", "", "Vegetarian", "Vegetarian since 2018."),
    ("Edna Fitzgerald", 3, "305", "Dairy", "Dairy-free, gluten-free", "Lactose intolerant."),
    ("Clarence Boyd", 3, "306", "", "Regular", "Independent - eats in dining room."),
    ("Rose Aguilar", 4, "401", "Sesame", "Low sodium", "Sesame allergy."),
    ("Milton Price", 4, "402", "", "Pureed", "Needs thickened liquids."),
    ("Alma Johansson", 4, "403", "", "Diabetic, low sugar", "Prefers sugar-free desserts."),
    ("Leonard Grant", 4, "404", "Shellfish", "Low sodium", "Shellfish allergy."),
    ("Irene Vasquez", 4, "405", "", "Vegetarian, gluten-free", "No meat, no gluten."),
    ("Chester Malone", 4, "406", "", "Low sodium", "Heart-healthy diet."),
]


def seed_demo(db: Database) -> dict:
    existing = db.query_one("SELECT COUNT(*) AS n FROM residents")
    if existing and existing["n"] > 0:
        return {"created": False, "residents": 0, "items": 0}

    timestamp = now_iso()
    building_ids: list[int] = []
    for name, notes in BUILDINGS:
        row = db.query_one("SELECT id FROM buildings WHERE name = ?", (name,))
        if row:
            building_ids.append(int(row["id"]))
        else:
            building_ids.append(
                db.insert("buildings", {"name": name, "notes": notes})
            )

    item_ids: dict[str, int] = {}
    for name, category, tags in MENU_ITEMS:
        item_ids[name] = db.insert(
            "meal_items",
            {
                "name": name,
                "category": category,
                "tags": tags,
                "notes": "",
                "active": 1,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

    rng = random.Random(42)
    resident_ids: list[int] = []
    for name, building_index, room, allergies, diet, notes in RESIDENTS:
        # Demo consent date between 6 and 30 months in the past.
        consent = (date.today() - timedelta(days=rng.randint(180, 900))).isoformat()
        resident_ids.append(
            db.insert(
                "residents",
                {
                    "name": name,
                    "building_id": building_ids[building_index - 1],
                    "room": room,
                    "allergies": allergies,
                    "diet": diet,
                    "notes": notes,
                    "consent_date": consent,
                    "active": 1,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
        )

    breakfast_pool = ["Scrambled eggs", "Oatmeal", "Gluten-free toast", "Greek yogurt", "Fresh fruit cup"]
    lunch_pool = ["Roast chicken", "Baked fish", "Mashed potatoes", "Brown rice", "Steamed broccoli", "Garden salad"]
    dinner_pool = ["Vegetable lasagna", "Gluten-free pasta", "Green beans", "Apple slices", "Tomato soup"]
    snack_pool = ["Banana", "Sugar-free jello", "Hummus with pita", "Vanilla pudding"]

    pools = {
        "breakfast": breakfast_pool,
        "lunch": lunch_pool,
        "dinner": dinner_pool,
        "snack": snack_pool,
    }

    for days_ago in (1, 0):
        service_date = (date.today() - timedelta(days=days_ago)).isoformat()
        for resident_id in resident_ids:
            for meal in ("breakfast", "lunch", "dinner"):
                ticket_id = db.insert(
                    "tickets",
                    {
                        "resident_id": resident_id,
                        "service_date": service_date,
                        "meal": meal,
                        "status": "delivered" if days_ago == 1 else "open",
                        "notes": "",
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
                picks = rng.sample(pools[meal], k=2)
                for item_name in picks:
                    db.insert(
                        "ticket_items",
                        {
                            "ticket_id": ticket_id,
                            "item_id": item_ids[item_name],
                            "qty": 1,
                            "note": "",
                        },
                    )
        if days_ago == 0:
            # A few tickets are already plated and ready.
            ready_ids = [t["id"] for t in db.query(
                "SELECT id FROM tickets WHERE service_date = ? ORDER BY id LIMIT 5",
                (service_date,),
            )]
            for ticket_id in ready_ids:
                db.execute(
                    "UPDATE tickets SET status = 'ready', updated_at = ? WHERE id = ?",
                    (timestamp, ticket_id),
                )

    return {"created": True, "residents": len(resident_ids), "items": len(item_ids)}
