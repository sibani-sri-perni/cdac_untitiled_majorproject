import re
import time
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from redis_client import redis_db
import config

def clean(v):
    return v.decode() if isinstance(v, bytes) else v

# ---------------- FORUM DISCOVERY ----------------

def discover_forums(page):
    print("\n[DISCOVER] Loading homepage...")

    page.goto(config.BASE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    soup = BeautifulSoup(page.content(), "html.parser")
    forums = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]

        if not href.startswith("/forums/"):
            continue

        if "." not in href:
            continue

        forums.add(urljoin(config.BASE_URL, href))

    print("[INFO] Forums found:", len(forums))
    return forums


def save_forums(forums):
    for f in forums:
        redis_db.sadd(config.FORUM_SET, f)

# ---------------- CRAWLER ----------------

def crawl_forums(page):

    start_time = time.time()

    forums = [clean(f) for f in redis_db.smembers(config.FORUM_SET)]
    print("[INFO] Total forums:", len(forums))

    for forum in forums:

        if redis_db.sismember(config.COMPLETED_FORUMS, forum):
            print("[SKIP]", forum)
            continue

        print("\n" + "=" * 80)
        print("[FORUM]", forum)

        page_no = 1
        empty_pages = 0

        while page_no <= config.MAX_PAGES_PER_FORUM:

            if time.time() - start_time > config.MAX_RUNTIME_SECONDS:
                print("[STOP] Max runtime reached")
                return

            url = forum if page_no == 1 else f"{forum}page-{page_no}"
            print("Opening:", url)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
            except Exception as e:
                print("[ERROR]", e)
                break

            soup = BeautifulSoup(page.content(), "html.parser")

            thread_urls = set()

            for a in soup.find_all("a", href=True):
                href = a["href"]

                if not re.search(r"\.\d+/?$", href):
                    continue

                if "/forums/" in href:
                    continue

                full = urljoin(config.BASE_URL, href)
                full = re.sub(r"/post-\d+$", "", full)
                thread_urls.add(full)

            new_threads = 0

            for t in thread_urls:
                if redis_db.sadd(config.THREAD_QUEUE, t):
                    new_threads += 1

            # ---------------- REQUIRED LOG 1 ----------------
            total_threads = redis_db.scard(config.THREAD_QUEUE)

            print("[FOUND]", len(thread_urls), "NEW:", new_threads)
            print("[TOTAL THREADS IN QUEUE]", total_threads)
            print("-" * 60)

            if new_threads < config.MIN_NEW_THREADS:
                empty_pages += 1
            else:
                empty_pages = 0

            if empty_pages >= config.EMPTY_PAGE_LIMIT:
                print("[SMART STOP] No new threads")
                break

            if not soup.select_one("a.pageNav-jump--next"):
                break

            page_no += 1

        redis_db.sadd(config.COMPLETED_FORUMS, forum)

        # ---------------- REQUIRED LOG 2 ----------------
        print("\n[DONE FORUM]")
        print("[FORUM THREADS TOTAL SO FAR]:", redis_db.scard(config.THREAD_QUEUE))
        print("=" * 80)

    print("\n[CRAWL COMPLETE]")
    print("Final Threads in queue:", redis_db.scard(config.THREAD_QUEUE))


# ---------------- MAIN ----------------

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        forums = discover_forums(page)
        save_forums(forums)

        crawl_forums(page)

        browser.close()


if __name__ == "__main__":
    main()