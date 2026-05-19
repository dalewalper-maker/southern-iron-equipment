"""Post one queued unit to Facebook Page AND Instagram Business via Graph API.
Runs as a GitHub Action on a schedule. Reads social_queue.json, posts the next
unposted unit to BOTH channels, marks each state independently, commits the queue back.

Env required:
  FB_PAGE_TOKEN  — never-expiring Page access token (has IG perms after token regen)
  FB_PAGE_ID     — Lift Boss JCB Lethbridge Page ID (908888912301091)
  PUBLIC_BASE    — site base URL for photo URLs (default southernironequipment.ca)
  IG_USER_ID     — optional override; otherwise auto-fetched from Page
"""
import json, os, sys, datetime, time
import urllib.request, urllib.parse, urllib.error

PAGE_TOKEN = os.environ["FB_PAGE_TOKEN"]
PAGE_ID = os.environ["FB_PAGE_ID"]
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://southernironequipment.ca")
IG_USER_ID_OVERRIDE = os.environ.get("IG_USER_ID")
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
        raise RuntimeError(f"HTTP {e.code} from Graph: {body}") from e


# ---------- Facebook Page ----------
def fb_upload_photo(url):
    """Upload unpublished photo by URL, returns media_fbid."""
    r = http("POST", f"{API}/{PAGE_ID}/photos",
             {"url": url, "published": "false", "access_token": PAGE_TOKEN})
    return r["id"]


def fb_post_unit(u):
    photo_urls = [f"{PUBLIC_BASE}/{p}" for p in u.get("photos", [])[:5]]
    print(f"[FB] Uploading {len(photo_urls)} photos...")
    media_ids = []
    for purl in photo_urls:
        try:
            mid = fb_upload_photo(purl)
            media_ids.append({"media_fbid": mid})
            time.sleep(0.5)
        except Exception as e:
            print(f"  [FB] photo upload failed for {purl}: {e}")
    payload = {"message": u["fb_message"], "access_token": PAGE_TOKEN}
    if media_ids:
        payload["attached_media"] = json.dumps(media_ids)
    r = http("POST", f"{API}/{PAGE_ID}/feed", payload)
    return r["id"]


# ---------- Instagram Business ----------
def ig_get_user_id():
    """Fetch Instagram Business Account ID linked to this FB Page (one-time)."""
    if IG_USER_ID_OVERRIDE:
        return IG_USER_ID_OVERRIDE
    r = http("GET", f"{API}/{PAGE_ID}",
             {"fields": "instagram_business_account", "access_token": PAGE_TOKEN})
    iba = r.get("instagram_business_account")
    if not iba or not iba.get("id"):
        raise RuntimeError("No Instagram Business Account linked to this Page. "
                           "Check FB Page Settings → Linked Accounts → Instagram.")
    return iba["id"]


def ig_create_child_container(ig_user_id, image_url):
    """Create a child container for a carousel item. Returns creation_id."""
    r = http("POST", f"{API}/{ig_user_id}/media", {
        "image_url": image_url,
        "is_carousel_item": "true",
        "access_token": PAGE_TOKEN,
    })
    return r["id"]


def ig_create_single_container(ig_user_id, image_url, caption):
    """Single-image post container."""
    r = http("POST", f"{API}/{ig_user_id}/media", {
        "image_url": image_url,
        "caption": caption,
        "access_token": PAGE_TOKEN,
    })
    return r["id"]


def ig_create_carousel_container(ig_user_id, child_ids, caption):
    """Wrap child containers into a carousel container."""
    r = http("POST", f"{API}/{ig_user_id}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": PAGE_TOKEN,
    })
    return r["id"]


def ig_wait_for_ready(creation_id, max_wait=60):
    """Poll status_code until container is FINISHED (or ERROR)."""
    for _ in range(max_wait):
        r = http("GET", f"{API}/{creation_id}",
                 {"fields": "status_code,status", "access_token": PAGE_TOKEN})
        status = r.get("status_code")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            raise RuntimeError(f"IG container processing error: {r.get('status')}")
        time.sleep(1)
    return False


def ig_publish(ig_user_id, creation_id):
    r = http("POST", f"{API}/{ig_user_id}/media_publish",
             {"creation_id": creation_id, "access_token": PAGE_TOKEN})
    return r["id"]


def ig_post_unit(u, caption):
    """Post unit photos as IG carousel (or single image if only 1 photo)."""
    ig_user_id = ig_get_user_id()
    photo_urls = [f"{PUBLIC_BASE}/{p}" for p in u.get("photos", [])[:10]]
    if not photo_urls:
        raise RuntimeError("No photos for IG post")
    print(f"[IG] Posting {len(photo_urls)} photo(s) to IG account {ig_user_id}...")
    if len(photo_urls) == 1:
        container_id = ig_create_single_container(ig_user_id, photo_urls[0], caption)
    else:
        child_ids = []
        for purl in photo_urls:
            try:
                cid = ig_create_child_container(ig_user_id, purl)
                child_ids.append(cid)
                time.sleep(0.5)
            except Exception as e:
                print(f"  [IG] child container failed for {purl}: {e}")
        if len(child_ids) < 2:
            # Fallback to single image if not enough children succeeded
            container_id = ig_create_single_container(ig_user_id, photo_urls[0], caption)
        else:
            container_id = ig_create_carousel_container(ig_user_id, child_ids, caption)
    print(f"[IG] Container {container_id} created. Waiting for processing...")
    if not ig_wait_for_ready(container_id):
        raise RuntimeError("IG container processing timed out")
    media_id = ig_publish(ig_user_id, container_id)
    return media_id


# ---------- Queue orchestration ----------
def ig_caption_from_fb(fb_message):
    """IG-flavored caption: same body, but IG accepts up to 30 hashtags and prefers
    them at the end. The FB message already includes hashtags + brand tags, so we
    can reuse mostly as-is. Trim to 2200 char IG limit if needed."""
    # IG hard cap is 2200 chars
    if len(fb_message) <= 2200:
        return fb_message
    return fb_message[:2196] + "…"


def main():
    with open(QUEUE) as f:
        q = json.load(f)

    # Find next unit needing either FB or IG post
    candidate = None
    for u in q["units"]:
        if not u.get("fb_posted") or not u.get("ig_posted"):
            if u.get("fb_posted") == "FAILED" and u.get("ig_posted") == "FAILED":
                continue
            candidate = u
            break

    if not candidate:
        print("Queue: nothing left to post on either channel.")
        return

    u = candidate
    print(f"Posting: {u['title']} ({u['slug']})")
    print(f"  FB state: {u.get('fb_posted')}, IG state: {u.get('ig_posted')}")

    # ---- FB post (skip if already posted) ----
    if not u.get("fb_posted") or u.get("fb_posted") == "FAILED":
        try:
            post_id = fb_post_unit(u)
            u["fb_posted"] = True
            u["fb_posted_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            u["fb_post_id"] = post_id
            print(f"  ✅ FB posted: {post_id}")
            print(f"  View: https://www.facebook.com/{post_id}")
        except Exception as e:
            print(f"  ❌ FB post failed: {e}")
            u.setdefault("fb_fail_count", 0)
            u["fb_fail_count"] += 1
            u["fb_last_error"] = str(e)
            if u["fb_fail_count"] >= 3:
                u["fb_posted"] = "FAILED"

    # ---- IG post (skip if already posted; skip if FB failed -- post both or neither
    #      this run, but allow IG retry next run if it failed alone) ----
    if not u.get("ig_posted") or u.get("ig_posted") == "FAILED":
        try:
            ig_caption = ig_caption_from_fb(u["fb_message"])
            ig_media_id = ig_post_unit(u, ig_caption)
            u["ig_posted"] = True
            u["ig_posted_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            u["ig_post_id"] = ig_media_id
            print(f"  ✅ IG posted: {ig_media_id}")
        except Exception as e:
            print(f"  ❌ IG post failed: {e}")
            u.setdefault("ig_fail_count", 0)
            u["ig_fail_count"] += 1
            u["ig_last_error"] = str(e)
            if u["ig_fail_count"] >= 3:
                u["ig_posted"] = "FAILED"

    with open(QUEUE, "w") as f:
        json.dump(q, f, indent=2)

    # Exit non-zero if BOTH failed so GH Actions surfaces a red check
    if u.get("fb_posted") not in (True, "FAILED") and u.get("ig_posted") not in (True, "FAILED"):
        sys.exit(1)


if __name__ == "__main__":
    main()
