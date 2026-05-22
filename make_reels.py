"""Generate a branded 9:16 video Reel for one unit.
Usage: python make_reels.py <slug> [--fast]
       python make_reels.py --all [budget_seconds]

Reads social_queue.json (has title, category, price, photos). Clean
professional slideshow: smooth crossfade dissolves between static letterbox-fit
photos (whole machine in frame, zero shake). Dark charcoal + gold, Lift Boss
JCB Lethbridge branded. Closes on the Lift Boss endcard + Dale's contact.
"""
import os, sys, json, subprocess, tempfile, shutil, time
from PIL import Image, ImageDraw, ImageFont, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True  # render even slightly-truncated JPGs

W, H = 1080, 1920
FPS = 30
BG = (13, 13, 15)
GOLD = (240, 168, 30)
GOLD_LT = (245, 184, 66)
TEXT = (238, 238, 240)
GRAY = (156, 156, 164)

def F(size, weight="Bold"):
    # Look for bundled repo fonts first (GitHub runners lack system Poppins),
    # then system fonts, then PIL default.
    for d in (os.path.join(SITE, "assets", "fonts"),
              "/usr/share/fonts/truetype/google-fonts"):
        for w in (weight, "Bold"):
            p = os.path.join(d, f"Poppins-{w}.ttf")
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()

SITE = os.path.dirname(os.path.abspath(__file__))
REELS_DIR = os.path.join(SITE, "assets", "reels")
QUEUE = os.path.join(SITE, "social_queue.json")
def _endcard_src():
    for n in ("reel-endcard.jpg", "reel-endcard.png"):
        p = os.path.join(SITE, "assets", n)
        if os.path.exists(p): return p
    return None
PHONE = "780-901-1573"
ADDR = "1065 - 36 Street North, Lethbridge, AB"

INTRO_DUR = 3.4
PHOTO_DUR = 3.2
END_DUR = 4.2
XFADE = 0.6


def ctext(d, cx, y, text, font, fill, spacing=0):
    if spacing:
        ws = [d.textlength(c, font=font) for c in text]
        x = cx - (sum(ws) + spacing * (len(text) - 1)) / 2
        for c, w in zip(text, ws):
            d.text((x, y), c, font=font, fill=fill); x += w + spacing
    else:
        b = d.textbbox((0, 0), text, font=font)
        d.text((cx - (b[2] - b[0]) / 2, y), text, font=font, fill=fill)
    b = d.textbbox((0, 0), text or "A", font=font)
    return y + (b[3] - b[1])


def wrap(d, text, font, max_w):
    out, cur = [], ""
    for wd in text.split():
        t = (cur + " " + wd).strip()
        if d.textlength(t, font=font) <= max_w: cur = t
        else:
            if cur: out.append(cur)
            cur = wd
    if cur: out.append(cur)
    return out


def base():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 6], fill=GOLD)
    d.rectangle([0, H - 6, W, H], fill=GOLD)
    return img, d


def fit_into(canvas, src_path, zone):
    zx, zy, zw, zh = zone
    im = Image.open(src_path).convert("RGB")
    iw, ih = im.size
    s = min(zw / iw, zh / ih)
    nw, nh = max(1, int(iw * s)), max(1, int(ih * s))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas.paste(im, (zx + (zw - nw) // 2, zy + (zh - nh) // 2))


def intro_png(unit, out):
    img, d = base()
    sale = unit.get("sale_info")
    eyebrow = ("PRICE DROP" if sale and sale.get("sale_badge") == "PRICE DROP"
               else "FEATURED DEAL" if sale else "NEW LISTING")
    # title = "<year make model> <Category>"
    title = unit["title"]
    cat = unit.get("category_label", "")
    full_title = f"{title} {cat}".strip()
    cy = 470
    ctext(d, W // 2, cy, eyebrow, F(48, "Bold"), GOLD, spacing=10); cy += 150
    tf = F(92, "Bold")
    for ln in wrap(d, full_title, tf, W - 130):
        cy = ctext(d, W // 2, cy, ln, tf, TEXT) + 16
    cy += 22
    # price
    price = unit.get("price_display", "Contact for pricing")
    cy = ctext(d, W // 2, cy, price, F(86, "Bold"), GOLD_LT) + 30
    if sale and sale.get("sale_reason"):
        cy = ctext(d, W // 2, cy, sale["sale_reason"], F(34, "Medium"), GOLD) + 30
    d.rectangle([W // 2 - 80, cy, W // 2 + 80, cy + 6], fill=GOLD); cy += 56
    cy = ctext(d, W // 2, cy, "Available now on our Lethbridge lot",
               F(42, "Medium"), TEXT) + 26
    ctext(d, W // 2, cy, ADDR, F(32, "Regular"), GRAY)
    # wordmark — full FB page name
    ctext(d, W // 2, H - 230, "LIFT BOSS JCB LETHBRIDGE", F(40, "Bold"), GOLD, spacing=2)
    img.save(out)


def photo_png(unit, photo_path, out):
    img, d = base()
    # photo upper area; title + price block sits in lower-middle (clear of edge)
    fit_into(img, photo_path, (40, 210, W - 80, 1120))
    cy = 1400
    d.rectangle([W // 2 - 56, cy, W // 2 + 56, cy + 5], fill=GOLD); cy += 36
    cat = unit.get("category_label", "")
    cy = ctext(d, W // 2, cy, f"{unit['title']} {cat}".strip(), F(50, "Bold"), TEXT) + 18
    ctext(d, W // 2, cy, unit.get("price_display", "Contact for pricing"), F(64, "Bold"), GOLD)
    img.save(out)


def endcard_png(out):
    img, d = base()
    src = _endcard_src()
    if src:
        fit_into(img, src, (24, 170, W - 48, 830))
    cy = 1090
    d.rectangle([W // 2 - 80, cy, W // 2 + 80, cy + 6], fill=GOLD); cy += 54
    cy = ctext(d, W // 2, cy, "CALL OR TEXT DALE", F(46, "Bold"), TEXT, spacing=3) + 26
    cy = ctext(d, W // 2, cy, PHONE, F(104, "Bold"), GOLD) + 42
    ctext(d, W // 2, cy, ADDR, F(32, "Regular"), GRAY)
    img.save(out)


def build_reel(slug, by_slug, fast=False):
    unit = by_slug.get(slug)
    if not unit:
        print(f"make_reels: unknown slug {slug}"); return False
    photos = unit.get("photos", [])
    paths = [os.path.join(SITE, p) for p in photos]
    paths = [p for p in paths if os.path.exists(p)]
    if len(paths) < 2:
        print(f"make_reels: {slug} <2 photos — skipping"); return False
    os.makedirs(REELS_DIR, exist_ok=True)
    work = tempfile.mkdtemp(prefix=f"reel-{slug}-")
    try:
        segs = []
        ip = os.path.join(work, "s_intro.png"); intro_png(unit, ip)
        segs.append((ip, INTRO_DUR))
        for i, pp in enumerate(paths):
            pg = os.path.join(work, f"s_p{i}.png"); photo_png(unit, pp, pg)
            segs.append((pg, PHOTO_DUR))
        ep = os.path.join(work, "s_end.png"); endcard_png(ep)
        segs.append((ep, END_DUR))

        inputs = []
        for png, dur in segs:
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur}", "-i", png]
        fc = []
        for i in range(len(segs)):
            fc.append(f"[{i}:v]settb=AVTB,fps={FPS},format=yuv420p,setsar=1[v{i}]")
        prev = "v0"; cum = segs[0][1]
        for i in range(1, len(segs)):
            off = cum - XFADE
            lbl = f"x{i}" if i < len(segs) - 1 else "vout"
            fc.append(f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE}:"
                      f"offset={off:.3f}[{lbl}]")
            cum = cum + segs[i][1] - XFADE
            prev = lbl
        out = os.path.join(REELS_DIR, f"{slug}.mp4")
        preset = "ultrafast" if fast else "medium"
        crf = "26" if fast else "23"
        cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + [
            "-filter_complex", ";".join(fc), "-map", "[vout]",
            "-c:v", "libx264", "-preset", preset, "-crf", crf,
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", out,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=150)
        print(f"make_reels: built {slug}.mp4 ({os.path.getsize(out)//1024} KB, "
              f"{cum:.1f}s, {len(paths)} photos, endcard={'yes' if _endcard_src() else 'FALLBACK'})")
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) < 2:
        print("usage: make_reels.py <slug> [--fast] | --all [budget]"); sys.exit(1)
    q = json.load(open(QUEUE))
    by_slug = {u["slug"]: u for u in q["units"]}
    if sys.argv[1] == "--all":
        budget = int(sys.argv[2]) if len(sys.argv) > 2 else 999999
        t0 = time.time(); built = skipped = 0
        for u in q["units"]:
            out = os.path.join(REELS_DIR, f"{u['slug']}.mp4")
            if os.path.exists(out):
                srcs = [os.path.join(SITE, p) for p in u.get("photos", [])]
                newest = max([os.path.getmtime(s) for s in srcs if os.path.exists(s)] or [0])
                if os.path.getmtime(out) >= newest:
                    skipped += 1; continue
            if time.time() - t0 > budget:
                print(f"make_reels: budget hit — built {built}, {skipped} cached"); print("MORE"); return
            try:
                if build_reel(u["slug"], by_slug): built += 1
            except Exception as e:
                print(f"make_reels: FAILED {u['slug']}: {e}")
        print(f"make_reels: done — built {built}, {skipped} current"); print("DONE")
    else:
        build_reel(sys.argv[1], by_slug, fast="--fast" in sys.argv)


if __name__ == "__main__":
    main()
