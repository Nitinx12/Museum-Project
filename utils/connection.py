from dotenv import load_dotenv
from pymongo import MongoClient
import os

load_dotenv()

# =========================================================
# POSTGRES
# =========================================================

POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE")
POSTGRES_USERNAME = os.getenv("POSTGRES_USERNAME")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

_required = {
    "POSTGRES_HOST": POSTGRES_HOST,
    "POSTGRES_PORT": POSTGRES_PORT,
    "POSTGRES_DATABASE": POSTGRES_DATABASE,
    "POSTGRES_USERNAME": POSTGRES_USERNAME,
    "POSTGRES_PASSWORD": POSTGRES_PASSWORD
}

_missing = [k for k, v in _required.items() if not v]

if _missing:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(_missing)}"
    )

# =========================================================
# MONGODB
# =========================================================

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB")

_required_mongo = {
    "MONGO_URI": MONGO_URI,
    "MONGO_DB": MONGO_DB
}

_missing_mongo = [k for k, v in _required_mongo.items() if not v]

if _missing_mongo:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(_missing_mongo)}"
    )

def get_mongo_db():
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB]