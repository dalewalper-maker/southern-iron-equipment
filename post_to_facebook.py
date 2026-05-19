"""Post one queued unit to Facebook Page via Graph API.
Runs as a GitHub Action on a schedule. Reads social_queue.json, posts the next
unposted unit, marks it posted, commits the queue back."""
import json, os, sys, datetime, time
import urllib.request, urllib.parse

PAGE_TOKEN = os.environ["FB_PAGE_TOKEN"]
PAGE_ID = os.environ["FB_PAGE_ID"]
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://southernironequipment.ca")
QUEUE = "social_queue.json"
API = "https://graph.facebook.com/v25.0"

def http(method, url, fields):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())

def upload_photo(url):
    """Uploads an unpublished photo by URL, returns media_fbid."""
    r = http("POST", f"{API}/{PAGE_ID}/photos",
             {"url": url, "published": "false", "access_token": PAGE_TOKEN})
    return r["id"]

def post_unit(u):
    photo_urls = [f"{PUBLIC_BASE}/{p}" for p in u.get("photos", [])[:5]]
    print(f"Uploading {len(photo_urls)} photos for {u['slug']}...")
    media_ids = []
    for purl in photo_urls:
        try:
            mid = upload_photo(purl)
            media_ids.append({"media_fbid": mid})
            time.sleep(0.5)
        except Exception as e:
            print(f"  photo upload failed for {purl}: {e}")
    payload = {"message": u["fb_message"], "access_token": PAGE_TOKEN}
    if media_ids:
        payload["attached_media"] = json.dumps(media_ids)
    print(f"Publishing feed post...")
    r = http("POST", f"{API}/{PAGE_ID}/feed", payload)
    return r["id"]

def main():
    with open(QUEUE) as f:
        q = json.load(f)
    pending = [u for u in q["units"] if not u.get("fb_posted")]
    if not pending:
        print("FB queue empty — nothing to post.")
        return
    u = pending[0]
    print(f"Posting: {u['title']} ({u['slug']})")
    try:
        post_id = post_unit(u)
        u["fb_posted"] = True
        u["fb_posted_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        u["fb_post_id"] = post_id
        with open(QUEUE, "w") as f:
            json.dump(q, f, indent=2)
        print(f"✅ Posted: {post_id}")
        # Print FB URL for visibility in Action log
        print(f"View: https://www.facebook.com/{post_id}")
    except Exception as e:
        print(f"❌ Post failed: {e}")
        # Mark as failed but don't block future tries — leave fb_posted false
        u.setdefault("fb_fail_count", 0)
        u["fb_fail_count"] += 1
        u["fb_last_error"] = str(e)
        if u["fb_fail_count"] >= 3:
            u["fb_posted"] = "FAILED"  # stop retrying after 3 fails
        with open(QUEUE, "w") as f:
            json.dump(q, f, indent=2)
        sys.exit(1)

if __name__ == "__main__":
    main()
