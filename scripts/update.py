#!/usr/bin/env python3
"""Daily Adopt Me data refresh for the Adopt Me Values & Trade app.

Reads the public value list from adoptmevalues.app, writes items.json (every item with
Normal/Neon/Mega values in all potion lanes), trends.json (latest value changes),
history.json (value snapshots for the charts) and downloads missing item images.
Usage: python3 scripts/update.py            (network)
       python3 scripts/update.py packed.json (offline test with a saved {"packed":..., "changes":...})
"""
import json, os, re, sys, time, urllib.request, urllib.parse, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://www.adoptmevalues.app"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131 Safari/537.36"}
IMAGE_TYPES = {"pets", "eggs", "other"}           # always get images
TOP_TYPES = {"vehicles", "strollers", "toys", "pet wear", "gifts", "food"}  # images for the top 40 by demand

def get(url, headers=None, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if a == tries - 1: raise
            time.sleep(3 + a * 3)

def slug(n):
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", n.lower().replace("&", "and")))

def extract_packed(text):
    s = text.index('{"packed":') + len('{"packed":')
    depth, i = 0, s
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                if text[i] == "\\": i += 1
                i += 1
        elif c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0: break
        i += 1
    return json.loads(text[s:i + 1])

def load_source():
    if len(sys.argv) > 1:
        d = json.load(open(sys.argv[1]))
        return d["packed"], d.get("changes")
    text = get(SITE + "/values?_rsc=x", {"RSC": "1"}).decode("utf-8")
    packed = extract_packed(text)
    try:
        changes = json.loads(get(SITE + "/api/value-changes"))
    except Exception:
        changes = None
    return packed, changes

def r2(x):
    return round(float(x), 4)

def main():
    packed, changes = load_source()
    rar, types = packed["rarities"], packed["types"]
    img_dir = os.path.join(ROOT, "images"); os.makedirs(img_dir, exist_ok=True)
    have = {f[:-4] for f in os.listdir(img_dir) if f.endswith(".png")}
    items, seen = [], set()
    want_img = []
    for row in packed["items"]:
        _id, name, image, ri, ti, ci, rank = row[:7]
        vals = [r2(v) for v in row[7:22]]
        s = slug(name)
        if s in seen: s = f"{s}-{_id}"
        seen.add(s)
        t = types[ti]
        it = {"id": str(_id), "n": name, "s": s, "r": rar[ri], "t": t, "d": rank, "v": vals}
        if t in IMAGE_TYPES or (t in TOP_TYPES and rank <= 40):
            want_img.append((s, image))
        items.append(it)
    # images
    got = 0
    for s, image in want_img:
        if s in have: continue
        if len(sys.argv) > 1: continue
        try:
            data = get(packed["imageBase"] + "/" + urllib.parse.quote(image), tries=2)
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                open(os.path.join(img_dir, s + ".png"), "wb").write(data); have.add(s); got += 1
        except Exception:
            pass
    for it in items:
        if it["s"] in have: it["i"] = 1
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).replace(microsecond=0).isoformat() + "Z"
    old = {}
    p = os.path.join(ROOT, "items.json")
    if os.path.exists(p):
        try: old = {x["s"]: x for x in json.load(open(p))["items"]}
        except Exception: old = {}
    if old and all(old.get(x["s"], {}).get("v") == x["v"] for x in items) and len(old) == len(items):
        print("values unchanged")
    json.dump({"updated": now, "source": "adoptmevalues.app", "count": len(items), "items": items},
              open(p, "w"), separators=(",", ":"), ensure_ascii=False)
    # trends: from the site's change feed, else from our previous items.json
    trends = {}
    if changes and changes.get("changed"):
        for c in changes["changed"]:
            rv = c.get("rvalue") or {}
            o, n = rv.get("oldVal"), rv.get("newVal")
            if o and n and o != n:
                trends[slug(c["name"])] = round((n - o) / o * 100, 1)
    elif old:
        for x in items:
            o = old.get(x["s"])
            if o and o["v"][0] and o["v"][0] != x["v"][0]:
                trends[x["s"]] = round((x["v"][0] - o["v"][0]) / o["v"][0] * 100, 1)
    tp = os.path.join(ROOT, "trends.json")
    prev_t = {}
    if os.path.exists(tp):
        try: prev_t = json.load(open(tp)).get("changes", {})
        except Exception: pass
    if trends or not prev_t:
        json.dump({"updated": now, "changes": trends}, open(tp, "w"), separators=(",", ":"))
    # history: one snapshot per 3 days, pets only, last 40 snapshots
    hp = os.path.join(ROOT, "history.json")
    hist = {"snapshots": []}
    if os.path.exists(hp):
        try: hist = json.load(open(hp))
        except Exception: pass
    today = now[:10]
    last = hist["snapshots"][-1]["date"] if hist["snapshots"] else "2000-01-01"
    if (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(last)).days >= 3:
        hist["snapshots"].append({"date": today, "v": {x["s"]: [x["v"][0], x["v"][5], x["v"][10]] for x in items if x["t"] == "pets"}})
        hist["snapshots"] = hist["snapshots"][-40:]
        json.dump(hist, open(hp, "w"), separators=(",", ":"))
    print(f"items {len(items)}, images new {got}, have {len(have)}, trends {len(trends)}")

if __name__ == "__main__":
    main()
