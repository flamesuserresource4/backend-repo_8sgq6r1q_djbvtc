import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import UserProfile, FoodItem, DailyLog, MealEntry, DailyTotals

app = FastAPI(title="Nutri Guide API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Nutri Guide API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


# -------- Utility: BMR/TDEE and Goal Calories ---------
class CaloriePlan(BaseModel):
    maintenance_calories: float
    goal_calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


def activity_multiplier(level: str) -> float:
    return {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }.get(level, 1.2)


def compute_plan(profile: UserProfile) -> CaloriePlan:
    # Mifflin-St Jeor
    if profile.gender == "male":
        bmr = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age + 5
    else:
        bmr = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age - 161

    tdee = bmr * activity_multiplier(profile.activity_level)

    # Goal adjustment
    adj = 0
    if profile.goal == "lose":
        adj = -0.2
    elif profile.goal == "gain":
        adj = 0.15

    goal_cals = tdee * (1 + adj)

    # Macro split: 30% protein, 40% carbs, 30% fat by calories
    protein_cal = 0.3 * goal_cals
    carbs_cal = 0.4 * goal_cals
    fat_cal = 0.3 * goal_cals

    return CaloriePlan(
        maintenance_calories=round(tdee, 0),
        goal_calories=round(goal_cals, 0),
        protein_g=round(protein_cal / 4, 0),
        carbs_g=round(carbs_cal / 4, 0),
        fat_g=round(fat_cal / 9, 0),
    )


# --------- Endpoints: Profiles ---------
@app.post("/api/profile", response_model=CaloriePlan)
def upsert_profile(profile: UserProfile):
    # Upsert by email
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    existing = db["userprofile"].find_one({"email": profile.email})
    if existing:
        db["userprofile"].update_one({"email": profile.email}, {"$set": profile.model_dump()})
    else:
        create_document("userprofile", profile)

    return compute_plan(profile)


@app.get("/api/profile/{email}")
def get_profile(email: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["userprofile"].find_one({"email": email}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    plan = compute_plan(UserProfile(**doc))
    return {"profile": doc, "plan": plan.model_dump()}


# --------- Endpoints: Food Catalog ---------
@app.post("/api/foods")
def add_food(item: FoodItem):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    inserted_id = create_document("fooditem", item)
    return {"id": inserted_id}


@app.get("/api/foods")
def list_foods(q: Optional[str] = None, limit: int = 50):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    query = {}
    if q:
        query = {"name": {"$regex": q, "$options": "i"}}
    docs = db["fooditem"].find(query).limit(limit)
    foods = []
    for d in docs:
        d["_id"] = str(d["_id"])
        foods.append(d)
    return foods


# --------- Endpoints: Daily Logs ---------
class LogRequest(BaseModel):
    email: str
    date: str  # YYYY-MM-DD


@app.get("/api/log/{email}/{log_date}")
def get_log(email: str, log_date: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["dailylog"].find_one({"email": email, "date": log_date})
    if not doc:
        return {"email": email, "date": log_date, "entries": [], "totals": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}}
    doc["_id"] = str(doc["_id"])
    return doc


class AddEntryRequest(BaseModel):
    email: str
    date: str
    entry: MealEntry


def recalc_totals(entries: List[dict]):
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    for e in entries:
        qty = e.get("quantity", 1)
        totals["calories"] += e.get("calories", 0) * qty
        totals["protein"] += e.get("protein", 0) * qty
        totals["carbs"] += e.get("carbs", 0) * qty
        totals["fat"] += e.get("fat", 0) * qty
    return {k: round(v, 1) for k, v in totals.items()}


@app.post("/api/log/entry")
def add_entry(payload: AddEntryRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Ensure log exists
    log = db["dailylog"].find_one({"email": payload.email, "date": payload.date})
    entry = payload.entry.model_dump()

    if log:
        entries = log.get("entries", [])
        entries.append(entry)
        totals = recalc_totals(entries)
        db["dailylog"].update_one(
            {"_id": log["_id"]},
            {"$set": {"entries": entries, "totals": totals}},
        )
        return {"status": "updated"}
    else:
        # Create new log
        totals = recalc_totals([entry])
        doc = {
            "email": payload.email,
            "date": payload.date,
            "entries": [entry],
            "totals": totals,
        }
        inserted_id = db["dailylog"].insert_one(doc).inserted_id
        return {"status": "created", "id": str(inserted_id)}


class DeleteEntryRequest(BaseModel):
    email: str
    date: str
    index: int


@app.delete("/api/log/entry")
def delete_entry(payload: DeleteEntryRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    log = db["dailylog"].find_one({"email": payload.email, "date": payload.date})
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    entries = log.get("entries", [])
    if payload.index < 0 or payload.index >= len(entries):
        raise HTTPException(status_code=400, detail="Invalid index")
    entries.pop(payload.index)
    totals = recalc_totals(entries)
    db["dailylog"].update_one({"_id": log["_id"]}, {"$set": {"entries": entries, "totals": totals}})
    return {"status": "deleted"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
