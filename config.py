BASE_URL = "https://www.blackhatworld.com"

# Redis keys
FORUM_SET         = "bhw:forums"
THREAD_QUEUE      = "bhw:thread_queue"
PROCESSED_THREADS = "bhw:processed_threads"
FAILED_THREADS    = "bhw:failed_threads"
COMPLETED_FORUMS  = "bhw:completed_forums"
THREAD_DATA       = "bhw:thread_data"
 

# Crawler limits
MAX_PAGES_PER_FORUM = 50
MAX_RUNTIME_SECONDS = 2 * 60 * 60

# Smart stop
EMPTY_PAGE_LIMIT = 3
MIN_NEW_THREADS = 1

# Scraper settings
REQUEST_DELAY_MIN = 1.0
REQUEST_DELAY_MAX = 2.0

