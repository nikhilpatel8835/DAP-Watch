import json, os, re, threading, time, random, requests
from http.server import BaseHTTPRequestHandler, HTTPServer

NTFY     = os.environ.get("NTFY_TOPIC", "evikash-token-dap-hack11xgdhd")
FTYPE    = 1                 # DAP
TARGETS  = [3859, 3856]
INTERVAL = 10
STATE    = "/tmp/state.json"

NAME_RE  = re.compile(r"(firm|retailer|shop|dealer|name)", re.I)
STOCK_RE = re.compile(r"(stock|avail|avi|balance|bal|qty|quantity|bag|beg)", re.I)
SKIP_RE  = re.compile(r"(id|code|type|dist|block|village|pincode|mobile)", re.I)
URL = ("https://evikas.mpkrishi.mp.gov.in/FarmerProfile/GetRetailerListById/"
       "?Block_Id={b}&District_id=409&Ferti_Product_Type_ID={f}"
       "&Is_Delivery=false&NoofBeg=1&Village_Id=0")
HDRS = {"Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Referer": "https://evikas.mpkrishi.mp.gov.in/FarmerProfile/FarmerProfileManagement",
        "Origin": "https://evikas.mpkrishi.mp.gov.in"}
S = requests.Session()
S.headers.update(HDRS)

def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)

def push(title, msg):
    try:
        S.post(f"https://ntfy.sh/{NTFY}", data=msg.encode(), timeout=20,
               headers={"Title": title, "Priority": "max", "Tags": "rotating_light",
                        "Click": "https://evikas.mpkrishi.mp.gov.in/FarmerProfile/FarmerProfileManagement"})
    except Exception as e:
        log(f"push fail: {e}")

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

def parse(js):
    out = {}
    for node in walk(js):
        name = next((v for k, v in node.items()
                     if isinstance(v, str) and NAME_RE.search(k) and v.strip()), None)
        if not name: continue
        nums = {k: v for k, v in node.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                and STOCK_RE.search(k) and not SKIP_RE.search(k)}
        if nums: out[name.strip()] = nums
    return out

def fetch(block):
    r = S.post(URL.format(b=block, f=FTYPE), timeout=30)
    r.raise_for_status()
    return r.json()

def serve():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
        def log_message(self, *a): pass
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), H).serve_forever()

def main():
    state, fails = None, 0
    while True:
        nxt, hits, ok = {}, [], False
        for i, block in enumerate(TARGETS):
            if i: time.sleep(4)
            try:
                parsed = parse(fetch(block))
                ok = True
            except Exception as e:
                log(f"block {block} fail: {e}"); continue
            log(f"block {block}: {len(parsed)} retailers")
            for retailer, fields in parsed.items():
                for f, val in fields.items():
                    key = f"{block}|{retailer}|{f}"
                    nxt[key] = val
                    if state is None: continue
                    prev = state.get(key)
                    if prev is None and val > 0:
                        hits.append(f"NEW — block {block}: {retailer}\n{f} = {val}")
                    elif prev is not None and val != prev:
                        hits.append(f"block {block}: {retailer}\n{f}: {prev} -> {val}")
            if state is not None:
                for key, prev in state.items():
                    if key.startswith(f"{block}|") and key not in nxt:
                        hits.append(f"GONE — {key.split('|')[1]} (was {prev})")
        if state is None:
            push("Watcher started", f"{len(nxt)} fields baseline. Alerts live.")
        elif hits:
            push(f"DAP CHANGE ({len(hits)})", "\n\n".join(hits)); log(f"ALERT x{len(hits)}")
        if ok:
            state, fails = nxt, 0
        else:
            fails += 1
            if fails == 3: push("e-Vikas poll failed", "Both blocks failing.")
        time.sleep(INTERVAL + random.uniform(-2, 2))

threading.Thread(target=serve, daemon=True).start()
main()
