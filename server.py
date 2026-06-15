from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="GlobuFlow API")
api_router = APIRouter(prefix="/api")


class WaitlistEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    source: Optional[str] = "hero"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WaitlistCreate(BaseModel):
    email: EmailStr
    source: Optional[str] = "hero"


class WaitlistResponse(BaseModel):
    id: str
    email: EmailStr
    source: Optional[str]
    created_at: datetime
    position: Optional[int] = None


class CareerApplication(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: EmailStr
    role: str
    message: Optional[str] = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CareerApplicationCreate(BaseModel):
    name: str
    email: EmailStr
    role: str
    message: Optional[str] = ""


@api_router.get("/")
async def root():
    return {"message": "GlobuFlow API — Flow without friction."}


@api_router.post("/waitlist", response_model=WaitlistResponse)
async def join_waitlist(payload: WaitlistCreate):
    email_lower = payload.email.lower().strip()
    existing = await db.waitlist.find_one({"email": email_lower})
    if existing:
        count = await db.waitlist.count_documents({})
        return WaitlistResponse(
            id=existing["id"],
            email=existing["email"],
            source=existing.get("source", "hero"),
            created_at=datetime.fromisoformat(existing["created_at"]) if isinstance(existing["created_at"], str) else existing["created_at"],
            position=count,
        )

    entry = WaitlistEntry(email=email_lower, source=payload.source or "hero")
    doc = entry.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.waitlist.insert_one(doc)
    count = await db.waitlist.count_documents({})
    return WaitlistResponse(
        id=entry.id,
        email=entry.email,
        source=entry.source,
        created_at=entry.created_at,
        position=count,
    )


@api_router.get("/waitlist/count")
async def waitlist_count():
    count = await db.waitlist.count_documents({})
    return {"count": count}


@api_router.get("/waitlist", response_model=List[WaitlistResponse])
async def list_waitlist():
    rows = await db.waitlist.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    out = []
    for r in rows:
        ts = r["created_at"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        out.append(WaitlistResponse(
            id=r["id"], email=r["email"], source=r.get("source", "hero"), created_at=ts
        ))
    return out


@api_router.post("/careers/apply")
async def apply_for_role(payload: CareerApplicationCreate):
    app_entry = CareerApplication(**payload.model_dump())
    doc = app_entry.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.career_applications.insert_one(doc)
    return {"ok": True, "id": app_entry.id}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
