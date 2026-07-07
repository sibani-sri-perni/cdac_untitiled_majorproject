import csv
import json
from redis_client import redis_db
import config

OUTPUT_FILE = "bhw_structured_recovered.csv"
FIELDS = ["title", "category", "author", "date", "replies", "content", "url", "scraped_at"]

def export_from_redis():
    raw = redis_db.hgetall(config.THREAD_DATA)
    print(f"[REDIS] {len(raw)} total scraped threads found in bhw:thread_data")

    written = 0
    skipped = 0

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for url, raw_json in raw.items():
            try:
                data = json.loads(raw_json)
                writer.writerow({field: data.get(field, "N/A") for field in FIELDS})
                written += 1
            except json.JSONDecodeError:
                skipped += 1

    print(f"[DONE] Wrote {written} rows -> {OUTPUT_FILE}")
    if skipped:
        print(f"[WARN] Skipped {skipped} entries with bad JSON")

if __name__ == "__main__":
    export_from_redis()