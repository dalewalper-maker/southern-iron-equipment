"""Post one queued unit to FB Page + IG Business. Debug-instrumented build."""
import json, os, sys, datetime, time
import urllib.request, urllib.parse, urllib.error
import traceback

LOG_PATH = "post_log.txt"
def log(msg):
    line = f"[{datetime.datetime.utcnow().isoformat()}Z] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

# Truncate log at start of each run
open(LOG_PATH, "w").close()

log("=== post_to_meta.py START ===")
log(f"Python: {sys.version}")

PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
PAGE_ID = os.environ.get("FB_PAGE_ID", "")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://southernironequipment.ca")
IG_USER_ID_OVERRIDE = os.environ.get("IG_USER_ID")
IG_ENABLED_RAW = os.environ.get("IG_ENABLED", "0")
IG_ENABLED = IG_ENABLED_RAW.strip() == "1"
# Reels: when "1", posts the unit's rendered video reel (FB Page video + IG Reel)
# instead of a photo carousel. Default OFF so a deploy never changes behaviour
# until we explicitly flip it on after a test run. Falls back to photo carousel
# for any unit that has no rendered reel.
REELS_ENABLED = os.environ.get("REELS_ENABLED", "0").strip() == "1"

log(f"FB_PAGE_TOKEN length: {len(PAGE_TOKEN)} (first 8: {PAGE_TOKEN[:8] if PAGE_TOKEN else 'EMPTY'})")
log(f"FB_PAGE_ID: '{PAGE_ID}'")
log(f"IG_ENABLED raw: '{IG_ENABLED_RAW}' -> bool: {IG_ENABLED}")
log(f"PUBLIC_BASE: {PUBLIC_BASE}")
log(f"REELS_ENABLED: {REELS_ENABLED}")

if not PAGE_TOKEN:
    log("FATAL: FB_PAGE_TOKEN env var is empty or missing")
    sys.exit(2)
if not PAGE_ID:
    log("FATAL: FB_PAGE_ID env var is empty or missing")
    sys.exit(2)

QUEUE = "social_queue.json"
API = "https://graph.facebook.com/v25.0"

def http(method, url, fields):
    data = urllib.parse.urlencode(fields).encode("utf-8") if fields else None
    if method == "GET" and fields:
        url = url + "?" + urllib.parse.urlencode(fields)
        data = None
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e

def fb_upload_photo(url):
    r = http("POST", f"{API}/{PAGE_ID}/photos",
             {"url": url, "published": "false", "access_token": PAGE_TOKEN})
    return r["id"]

def fb_post_unit(u):
    photo_urls = [f"{PUBLIC_BASE}/{p}" for p in u.get("photos", [])[:5]]
    log(f"[FB] Uploading {len(photo_urls)} photos for {u['slug']}")
    media_ids = []
    for purl in photo_urls:
        try:
            mid = fb_upload_photo(purl)
            media_ids.append({"media_fbid": mid})
            log(f"  [FB] photo uploaded: {mid}")
            time.sleep(0.5)
        except Exception as e:
            log(f"  [FB] photo FAIL {purl}: {e}")
    payload = {"message": u["fb_message"], "access_token": PAGE_TOKEN}
    if media_ids:
        payload["attached_media"] = json.dumps(media_ids)
    log(f"[FB] Publishing feed post with {len(media_ids)} photos...")
    r = http("POST", f"{API}/{PAGE_ID}/feed", payload)
    return r["id"]

def ig_get_user_id():
    if IG_USER_ID_OVERRIDE:
        return IG_USER_ID_OVERRIDE
    r = http("GET", f"{API}/{PAGE_ID}",
             {"fields": "instagram_business_account", "access_token": PAGE_TOKEN})
    iba = r.get("instagram_business_account")
    if not iba or not iba.get("id"):
        raise RuntimeError("No IG Business Account linked to this Page")
    return iba["id"]

def ig_child(ig_id, image_url):
    r = http("POST", f"{API}/{ig_id}/media",
             {"image_url": image_url, "is_carousel_item": "true", "access_token": PAGE_TOKEN})
    return r["id"]

def ig_single(ig_id, image_url, caption):
    r = http("POST", f"{API}/{ig_id}/media",
             {"image_url": image_url, "caption": caption, "access_token": PAGE_TOKEN})
    return r["id"]

def ig_carousel(ig_id, child_ids, caption):
    r = http("POST", f"{API}/{ig_id}/media",
             {"media_type": "CAROUSEL", "children": ",".join(child_ids),
              "caption": caption, "access_token": PAGE_TOKEN})
    return r["id"]

def ig_wait(creation_id, max_wait=60, interval=1):
    for i in range(max_wait):
        r = http("GET", f"{API}/{creation_id}",
                 {"fields": "status_code,status", "access_token": PAGE_TOKEN})
        s = r.get("status_code")
        if s == "FINISHED": return True
        if s == "ERROR": raise RuntimeError(f"IG processing error: {r.get('status')}")
        time.sleep(interval)
    return False

def ig_publish(ig_id, creation_id):
    r = http("POST", f"{API}/{ig_id}/media_publish",
             {"creation_id": creation_id, "access_token": PAGE_TOKEN})
    return r["id"]

def ig_post_unit(u, caption):
    ig_id = ig_get_user_id()
    log(f"[IG] User ID: {ig_id}")
    photo_urls = [f"{PUBLIC_BASE}/{p}" for p in u.get("photos", [])[:10]]
    if not photo_urls: raise RuntimeError("No photos")
    log(f"[IG] Posting {len(photo_urls)} photos")
    if len(photo_urls) == 1:
        container = ig_single(ig_id, photo_urls[0], caption)
    else:
        children = []
        for purl in photo_urls:
            try:
                children.append(ig_child(ig_id, purl))
                time.sleep(0.5)
            except Exception as e:
                log(f"  [IG] child FAIL {purl}: {e}")
        if len(children) < 2:
            container = ig_single(ig_id, photo_urls[0], caption)
        else:
            container = ig_carousel(ig_id, children, caption)
    log(f"[IG] Container {container} created, waiting...")
    if not ig_wait(container): raise RuntimeError("IG processing timeout")
    media_id = ig_publish(ig_id, container)
    return media_id

# ---- Reels: post the unit's rendered video instead of a photo carousel ----
def reel_rel(slug):
    return f"assets/reels/{slug}.mp4"

def has_reel(slug):
    return os.path.exists(reel_rel(slug))

def fb_post_reel(u):
    """Post the unit's rendered reel as a Facebook Page video."""
    url = f"{PUBLIC_BASE}/{reel_rel(u['slug'])}"
    log(f"[FB] Posting reel video: {url}")
    r = http("POST", f"{API}/{PAGE_ID}/videos",
             {"file_url": url, "description": u["fb_message"],
              "access_token": PAGE_TOKEN})
    return r["id"]

def ig_post_reel(u, caption):
    """Post the unit's rendered reel as an Instagram Reel."""
    ig_id = ig_get_user_id()
    url = f"{PUBLIC_BASE}/{reel_rel(u['slug'])}"
    log(f"[IG] Creating Reel container: {url}")
    r = http("POST", f"{API}/{ig_id}/media",
             {"media_type": "REELS", "video_url": url, "caption": caption,
              "access_token": PAGE_TOKEN})
    container = r["id"]
    log(f"[IG] Reel container {container} created — waiting for processing...")
    # Reels transcode takes longer than photos — poll up to ~10 min
    if not ig_wait(container, max_wait=120, interval=5):
        raise RuntimeError("IG Reel processing timed out")
    media_id = ig_publish(ig_id, container)
    return media_id

def main():
    log("Loading queue file...")
    with open(QUEUE) as f:
        q = json.load(f)
    log(f"Queue loaded: {len(q['units'])} units")

    candidate = None
    skipped_no_photos = []
    for u in q["units"]:
        fb_done = u.get("fb_posted") in (True, "FAILED")
        ig_done = (not IG_ENABLED) or u.get("ig_posted") in (True, "FAILED")
        if fb_done and ig_done:
            continue
        # Skip units with no photos. A photoless unit posts a broken text-only
        # FB post and fails IG outright ("No photos"). Skip it (do NOT mark it
        # posted) so it becomes eligible automatically once photos are added.
        if not u.get("photos"):
            skipped_no_photos.append(u.get("slug"))
            continue
        candidate = u
        break

    if skipped_no_photos:
        log(f"Skipped {len(skipped_no_photos)} photoless unit(s): {', '.join(skipped_no_photos)}")

    if not candidate:
        log("Queue: nothing left to post (all remaining units are posted or photoless).")
        return

    u = candidate
    log(f"CANDIDATE: {u['title']} ({u['slug']}) score={u.get('_priority_score')}")
    log(f"  fb_posted={u.get('fb_posted')} ig_posted={u.get('ig_posted')}")

    use_reel = REELS_ENABLED and has_reel(u["slug"])
    log(f"  REELS_ENABLED={REELS_ENABLED}, reel_exists={has_reel(u['slug'])} -> use_reel={use_reel}")

    if not u.get("fb_posted") or u.get("fb_posted") == "FAILED":
        try:
            post_id = fb_post_reel(u) if use_reel else fb_post_unit(u)
            u["fb_posted"] = True
            u["fb_posted_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            u["fb_post_id"] = post_id
            log(f"  ✅ FB posted: {post_id}")
            log(f"  View: https://www.facebook.com/{post_id}")
        except Exception as e:
            log(f"  ❌ FB FAIL: {e}")
            log(f"  Traceback: {traceback.format_exc()}")
            u.setdefault("fb_fail_count", 0)
            u["fb_fail_count"] += 1
            u["fb_last_error"] = str(e)[:500]
            if u["fb_fail_count"] >= 3:
                u["fb_posted"] = "FAILED"

    if IG_ENABLED and (not u.get("ig_posted") or u.get("ig_posted") == "FAILED"):
        try:
            caption = u["fb_message"][:2200]
            # IG reels disabled per user request (2026-06-10): Instagram posts
            # photo carousels only — never video reels. FB reels unaffected.
            media_id = ig_post_unit(u, caption)
            u["ig_posted"] = True
            u["ig_posted_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            u["ig_post_id"] = media_id
            log(f"  ✅ IG posted: {media_id}")
        except Exception as e:
            log(f"  ❌ IG FAIL: {e}")
            log(f"  Traceback: {traceback.format_exc()}")
            u.setdefault("ig_fail_count", 0)
            u["ig_fail_count"] += 1
            u["ig_last_error"] = str(e)[:500]
            if u["ig_fail_count"] >= 3:
                u["ig_posted"] = "FAILED"
    elif not IG_ENABLED:
        log("[IG] Skipped — IG_ENABLED=0")

    log("Writing queue back...")
    with open(QUEUE, "w") as f:
        json.dump(q, f, indent=2)
    log("=== post_to_meta.py END ===")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL in main(): {e}")
        log(traceback.format_exc())
        sys.exit(3)
