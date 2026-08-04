import sys, os, json, importlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import fetch_feeds as ff
FIX = os.path.join(os.path.dirname(__file__), "fixtures")
def fake_http_get(url):
    if "news.google.com" in url: fn = "gnews.xml"
    elif "zeit" in url or "taz" in url: fn = "atom.xml"
    elif "sueddeutsche.de/rss/Wirtschaft" in url: raise OSError("simulierter Ausfall")
    else: fn = "rss2.xml"
    return open(os.path.join(FIX, fn), "rb").read()
ff.http_get = fake_http_get
ff.main()
d = json.load(open(os.path.join(ff.DATA, "global.json"), encoding="utf-8"))
he = json.load(open(os.path.join(ff.DATA, "land-he.json"), encoding="utf-8"))
eu = json.load(open(os.path.join(ff.DATA, "europa.json"), encoding="utf-8"))
de = json.load(open(os.path.join(ff.DATA, "deutschland.json"), encoding="utf-8"))
mv = json.load(open(os.path.join(ff.DATA, "land-mv.json"), encoding="utf-8"))
def titles(doc, mid): return [i["t"] for s in doc["sources"] if s["id"]==mid for i in s["items"]]
print("GLOBAL ts:", titles(d,"ts"))
print("GLOBAL gn:", titles(d,"gn"), "| Inhaltsangabe:", [i["s"] for s in d["sources"] if s["id"]=="gn" for i in s["items"]])
print("EUROPA ts:", titles(eu,"ts"))
print("DEUTSCHLAND ts:", titles(de,"ts"))
print("HESSEN ts:", titles(he,"ts"), "| HESSEN gn:", titles(he,"gn"))
print("MV zeit (Atom):", titles(mv,"zeit"))
print("SZ stale?", [ (s["id"], s.get("stale"), s.get("err"), len(s["items"])) for s in d["sources"] if s["id"]=="sz"])
print("HTML raus?", all("<" not in i["s"] for s in d["sources"] for i in s["items"]))
