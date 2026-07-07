import re
import csv
import os
import json
import time
import random
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from redis_client import redis_db
import config

# ---------------- CONFIG ----------------
OUTPUT_DIR = "data"
os.makedirs(OUTPUT_DIR, exist_ok=True)
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"bhw_structured_{RUN_ID}_{os.getpid()}.csv")
FIELDS = ["title", "category", "author", "date", "replies", "content", "url", "scraped_at"]

# Tracks URLs that are currently being scraped by some worker, so a second
# worker doesn't grab the same URL out of the queue's race window.
IN_PROGRESS_SET = "bhw:in_progress"

# Running total of successful scrapes across all workers combined.
# No target/cap anymore - workers run until the queue is empty.
SCRAPED_COUNTER = "bhw:scraped_count"

# ---------------- HELPERS ----------------

def clean(v):
    return v.decode() if isinstance(v, bytes) else v


def is_valid_thread_url(url):
    return not any(x in url for x in [
        "/members/",
        "/account/",
        "/conversations/",
        "/attachments/",
        "/help/",
    ])


def write_csv(data):
    file_exists = os.path.isfile(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)


# ---------------- EXTRACTION ----------------

def extract_title(soup):
    el = soup.select_one("h1.p-title-value") or soup.select_one("h1")
    return el.get_text(strip=True) if el else "N/A"


def extract_category(soup):
    crumbs = soup.select(".p-breadcrumbs li")
    if len(crumbs) >= 2:
        return crumbs[-2].get_text(strip=True)
    return crumbs[-1].get_text(strip=True) if crumbs else "N/A"


def extract_author(soup):
    for sel in [
        "article.message--firstPost .username",
        "article.message--firstPost .message-name a",
        "article.message--firstPost [data-user-id]",
    ]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)

    for sel in [
        ".p-description .username",
        ".threadStarterInfo .username",
        ".message-userDetails .username",
        "a.username[data-user-id]",
    ]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)

    return "N/A"


def extract_date(soup):
    first_post = soup.select_one("article.message--firstPost")
    if first_post:
        time_el = first_post.find("time")
        if time_el:
            return time_el.get("datetime") or time_el.get_text(strip=True)

    pairs = [dl for dl in soup.find_all("dl")
             if "pairs--justified" in " ".join(dl.get("class", []))]
    date_pattern = re.compile(r'\b(\w{3,9}\s+\d{1,2},\s*\d{4}|\d{4}-\d{2}-\d{2})\b')
    for dl in pairs:
        text = dl.get_text(strip=True)
        match = date_pattern.search(text)
        if match:
            return match.group(1)

    for t in soup.find_all("time"):
        if t.get("datetime"):
            return t["datetime"]

    return "N/A"


def extract_replies(soup):
    for dl in soup.find_all("dl"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if dt and dd and "repl" in dt.get_text(strip=True).lower():
            return dd.get_text(strip=True)

    pairs = [dl for dl in soup.find_all("dl")
             if "pairs--justified" in " ".join(dl.get("class", []))]
    date_pattern = re.compile(r'\b\w{3,9}\s+\d{1,2},\s*\d{4}\b')
    for dl in pairs:
        text = dl.get_text(strip=True).replace(",", "")
        if date_pattern.search(text):
            continue
        if text.isdigit():
            return text

    match = re.search(r"([\d,]+)\s*[Rr]eplies?", soup.get_text(" ", strip=True))
    return match.group(1).replace(",", "") if match else "N/A"


def extract_content(soup):
    for sel in [
        "article.message--firstPost .bbWrapper",
        "article.message--firstPost .message-body",
        "article.message--firstPost [itemprop='text']",
        ".message-body .bbWrapper",
        ".bbWrapper",
    ]:
        el = soup.select_one(sel)
        if el:
            return re.sub(r"\s+", " ", el.get_text()).strip()[:5000]
    return "N/A"


# ---------------- SCRAPER ----------------

def scrape_thread(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_selector("article.message--firstPost", timeout=5000)
        except:
            pass

        page.wait_for_timeout(1000)

        if "just a moment" in page.content().lower():
            print("[BLOCKED]", url)
            return None

        soup = BeautifulSoup(page.content(), "html.parser")

        return {
            "title":      extract_title(soup),
            "category":   extract_category(soup),
            "author":     extract_author(soup),
            "date":       extract_date(soup),
            "replies":    extract_replies(soup),
            "content":    extract_content(soup),
            "url":        url,
            "scraped_at": datetime.now().isoformat()
        }

    except Exception as e:
        print("[ERROR]", url, str(e)[:100])
        return None


# ---------------- MAIN ----------------

def run_worker():

    # Small random delay on startup so 3 terminals launched together
    # don't all hit the site in the exact same instant.
    time.sleep(random.uniform(0, 4))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )

        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins',   {get: () => [1, 2, 3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}};
        """)

        page = context.new_page()

        worker_id = os.getpid()

        print(f"\n WORKER {worker_id} STARTED")
        print("Output file:", OUTPUT_FILE)
        print("Queue size :", redis_db.scard(config.THREAD_QUEUE))
        print("Scraped so far (all workers combined):", int(redis_db.get(SCRAPED_COUNTER) or 0))

        count = 0
        errors = 0
        skipped = 0

        try:
            while True:
                url = redis_db.spop(config.THREAD_QUEUE)

                if not url:
                    print("\n[DONE] Queue empty")
                    break

                url = clean(url)

                # Already done by some worker in a previous run
                if redis_db.sismember(config.PROCESSED_THREADS, url):
                    skipped += 1
                    continue

                # Junk URL types we never want in the output
                if not is_valid_thread_url(url):
                    redis_db.sadd(config.PROCESSED_THREADS, url)
                    skipped += 1
                    continue

                # Another worker grabbed this URL just before us — skip,
                # don't re-scrape it, and don't mark it processed (the
                # worker holding it will do that itself when it finishes).
                if redis_db.sismember(IN_PROGRESS_SET, url):
                    skipped += 1
                    continue

                redis_db.sadd(IN_PROGRESS_SET, url)

                print(f"[W{worker_id}] {count + 1} → {url}")

                data = scrape_thread(page, url)

                if data:
                    redis_db.hset(config.THREAD_DATA, url, json.dumps(data, ensure_ascii=False))
                    write_csv(data)
                    redis_db.incr(SCRAPED_COUNTER)

                    print(" ✔ Title   :", data["title"][:60])
                    print(" ✔ Category:", data["category"])
                    print(" ✔ Author  :", data["author"])
                    print(" ✔ Date    :", data["date"])
                    print(" ✔ Replies :", data["replies"])

                    count += 1
                else:
                    errors += 1
                    redis_db.sadd(config.FAILED_THREADS, url)

                redis_db.srem(IN_PROGRESS_SET, url)
                redis_db.sadd(config.PROCESSED_THREADS, url)

                time.sleep(random.uniform(
                    config.REQUEST_DELAY_MIN,
                    config.REQUEST_DELAY_MAX
                ))

        except KeyboardInterrupt:
            print("\n[INTERRUPTED] Shutting down cleanly...")

        finally:
            browser.close()

        print(f"\n====== WORKER {worker_id} DONE ======")
        print("Scraped :", count)
        print("Errors  :", errors)
        print("Skipped :", skipped)
        print("=====================================")


if __name__ == "__main__":
    run_worker()
