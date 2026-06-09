"""
backfill_timestamps.py
Run this once to permanently add an 'updated_at' column to all existing MongoDB documents.
"""

import sys
from datetime import datetime
from pathlib import Path

# Auto-detect project root so imports work perfectly
current = Path(__file__).resolve().parent
for _ in range(6):
    if (current / "configs" / "connection.py").exists():
        if str(current) not in sys.path:
            sys.path.insert(0, str(current))
        break
    current = current.parent

from pymongo import MongoClient
from configs.connection import MONGO_URI, MONGO_DB

ISO_FMT = "%Y-%m-%dT%H:%M:%S"

def main():
    collections = [
        "museum", "museum_hours", "subject", 
        "canvas_size", "work", "product_size", "artist"
    ]
    
    print(f"Connecting to MongoDB database: '{MONGO_DB}'...")
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    
    # Generate one exact timestamp for this entire backfill batch
    current_time = datetime.now().strftime(ISO_FMT)
    print(f"Timestamp to apply: {current_time}\n")
    print("-" * 50)
    
    total_updated = 0
    for col in collections:
        # Find all documents where 'updated_at' is missing and add it
        result = db[col].update_many(
            {"updated_at": {"$exists": False}},
            {"$set": {"updated_at": current_time}}
        )
        print(f"Collection '{col:<15}' : Updated {result.modified_count} rows.")
        total_updated += result.modified_count
        
    print("-" * 50)
    print(f"DONE! Total rows updated: {total_updated}")
    
    client.close()

if __name__ == "__main__":
    main()