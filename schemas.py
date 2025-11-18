"""
Database Schemas for Nutri Guide

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
- UserProfile -> "userprofile"
- FoodItem -> "fooditem"
- DailyLog -> "dailylog"
- MealEntry -> embedded within DailyLog.entries
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal


class UserProfile(BaseModel):
    """
    User profile and goal settings
    Collection: userprofile
    """
    email: str = Field(..., description="Unique email identifier")
    name: Optional[str] = Field(None, description="Full name")
    age: int = Field(..., ge=10, le=120, description="Age in years")
    gender: Literal["male", "female"] = Field(..., description="Biological sex for BMR calc")
    height_cm: float = Field(..., gt=0, description="Height in centimeters")
    weight_kg: float = Field(..., gt=0, description="Current weight in kilograms")
    activity_level: Literal[
        "sedentary", "light", "moderate", "active", "very_active"
    ] = Field(..., description="Activity multiplier for TDEE")
    goal: Literal["lose", "maintain", "gain"] = Field(
        "maintain", description="Calorie goal direction"
    )


class FoodItem(BaseModel):
    """
    Food catalog item (per 100g or per serving)
    Collection: fooditem
    """
    name: str = Field(..., description="Food name")
    calories: float = Field(..., ge=0, description="kcal per serving")
    protein: float = Field(0, ge=0, description="grams per serving")
    carbs: float = Field(0, ge=0, description="grams per serving")
    fat: float = Field(0, ge=0, description="grams per serving")
    serving: str = Field("1 serving", description="Serving description, e.g., 100g or 1 cup")
    source: Optional[str] = Field(None, description="origin: built-in or user")
    created_by: Optional[str] = Field(None, description="email of creator if custom")


class MealEntry(BaseModel):
    """
    Single meal entry embedded in a daily log
    """
    food_id: Optional[str] = Field(None, description="Referenced FoodItem _id as string")
    name: str = Field(..., description="Food name at time of logging")
    calories: float = Field(..., ge=0)
    protein: float = Field(0, ge=0)
    carbs: float = Field(0, ge=0)
    fat: float = Field(0, ge=0)
    quantity: float = Field(1, gt=0, description="Multiplier of serving")
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] = "breakfast"


class DailyTotals(BaseModel):
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0


class DailyLog(BaseModel):
    """
    Daily log of meals for a user and date
    Collection: dailylog
    """
    email: str = Field(..., description="User email")
    date: str = Field(..., description="YYYY-MM-DD")
    entries: List[MealEntry] = []
    totals: DailyTotals = DailyTotals()
