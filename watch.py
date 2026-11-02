import json, os, re, time, requests

NTFY     = os.environ["NTFY_TOPIC"]
DIST     = 409
FTYPE    = 5          # DAP
STATE    = "state.json"
TARGETS  = [3859, 3856]
COOLDOWN = 1800       # seconds before the same retailer can alert again

NAME_RE  = re.compile(r"(firm|retailer|shop|dealer|name)", re.I)
STOCK_RE = re.compile(r"(stock|avail|avi|balance|bal|qty|quantity|bag|beg)", re.I)
SKIP_RE  = re.compile(r"(id|code|type|dist|block|village|pincode|mobile)", re.I)

URL = ("https://evikas.mpkrishi.mp.gov.in/FarmerProfile/GetRetailerListById/"
       "?Block_Id={b}&District_id=409&Ferti_Product_Type_ID=5"
       "&Is_Delivery=false&NoofBeg=1&Village_Id=0")

HDRS = {"Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Referer": "https://evikas.mpkrishi.mp.gov.in/FarmerProfile/FarmerProfileManagement",
        "Origin": "https://evikas.mpkrishi.mp.gov.in"}

def push(title, msg):
    requests.post(f"https://ntfy.sh/{NTFY}", data=msg.encode(),
        headers={"Title": title, "Priority": "max", "Tags": "rotating_light",
                 "Click": "https://evikas.mpkrishi.mp.gov.in/FarmerProfile/FarmerProfileManagement"},
        timeout=30)

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)

def parse(js):
    out = {}
    for node in walk(js):
        name = next((v for k, v in node.items()
                     if isinstance(v, str) and NAME_RE.search(k) and v.strip()), None)
        if not name:
            continue
        nums = {k: v for k, v in node.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                and STOCK_RE.search(k) and not SKIP_RE.search(k)}
        if nums:
            out[name.strip()] = nums
    return out

def main():
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    hits, changed, fails = [], False, 0

    for block in TARGETS:
        try:
            r = requests.post(URL.format(b=block), headers=HDRS, timeout=45)
            if r.status_code != 200:
                print(f"block {block}: HTTP {r.status_code}")
                fails += 1
                continue
            js = r.json()
        except Exception as e:
            print(f"block {block}: {e}")
            fails += 1
            continue

        parsed = parse(js)
        print(f"--- block {block}: {len(parsed)} retailers parsed")
        print(json.dumps(parsed, indent=1, ensure_ascii=False)[:3000])

        for retailer, fields in parsed.items():
            for f, raw in fields.items():
                val  = float(raw)
                key  = f"{block}|{retailer}|{f}"
                prev = float(state.get(key, {}).get("v", 0))
                last = state.get(key, {}).get("t", 0)
                if val > 0 and (prev <= 0 or val > prev) and time.time() - last > COOLDOWN:
                    hits.append(f"Block {block}: {retailer}\n{f} = {val:g} (was {prev:g})")
                    state[key] = {"v": val, "t": time.time()}
                    changed = True
                elif val != prev:
                    state[key] = {"v": val, "t": last}
                    changed = True

    if hits:
        push("DAP STOCK AVAILABLE", "\n\n".join(hits))
        print("ALERT SENT")
    if changed:
        json.dump(state, open(STATE, "w"), indent=1)
    if fails == len(TARGETS):
        push("e-Vikas poll failed", "Both blocks errored — check the portal.")

main()
