#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Merricksblatt – Feed-Sammler für GitHub Actions
================================================
Läuft zeitgesteuert im GitHub-Runner, ruft die RSS-Feeds der Verlage sowie
Google-News-Suchen serverseitig ab (dort gibt es keine CORS-Beschränkung),
sortiert die Beiträge in die Rubriken ein und schreibt fertige JSON-Dateien
nach data/. Die Webseite lädt anschließend nur noch diese eigenen Dateien.

Nur Python-Standardbibliothek – keine Abhängigkeiten, kein pip.

Robustheit:
- Antwortet ein Feed nicht, bleiben die zuletzt erfolgreich geladenen
  Beiträge dieser Quelle erhalten (Kennzeichnung "stale": true).
- Jeder Lauf schreibt data/meta.json mit dem Status jedes einzelnen Abrufs –
  dort lässt sich jederzeit nachsehen, welche Quelle gerade klemmt.
"""

import concurrent.futures as cf
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, wie Gecko) "
      "MerricksblattBot/2.0 (+https://merricksblatt.janrickmer.de)")
TIMEOUT = 25
MAX_ITEMS = 15          # je Quelle und Rubrik gespeicherte Beiträge
SUMMARY_MAX = 320       # Zeichenobergrenze der Inhaltsangabe (RSS-Teaser)

# ---- KI-Zusammenfassungen serverseitig im Datenlauf ------------------------
# GitHub Models wurde zum 30.07.2026 vollständig abgeschaltet (HTTP 410).
# Ersatzweg: Der Runner ruft Pollinations.AI auf – serverseitig, im
# Anfragekörper (keine Adresslängen-Grenze) und bewusst langsam getaktet,
# damit die Anonym-Drossel (~1 Anfrage / 15 s) nie greift. Scheitert ein
# Aufruf, bleibt die letzte Fassung erhalten; die Seite hat zudem ihre
# lokale Ersatzfassung. Optionale Härtung ohne Code-Änderung: Liegen die
# Repository-Secrets CF_ACCOUNT_ID und CF_API_TOKEN vor (kostenloses
# Cloudflare-Konto, Workers AI: 10.000 Neurons/Tag gratis mit harter
# Abschaltung), nutzt der Lauf zuerst Cloudflare und Pollinations nur
# noch als Rückfalle.
POLLI_URL = "https://text.pollinations.ai/openai"
POLLI_PAUSE = 16        # Sekunden zwischen Pollinations-Aufrufen (Drossel-Takt)
CF_MODEL_DEFAULT = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
SUM_MAIN_MIN = 110      # Minuten: Globales/Europa/Deutschland neu nach ~2 Stunden
SUM_LAND_MIN = 350      # Minuten: Bundesländer/Kommune neu nach ~6 Stunden
SUM_MAX_CALLS = 24      # harte Obergrenze an KI-Aufrufen je Lauf

# ---------------------------------------------------------------- Medien ---

MEDIA = {
    "ts":      ("Tagesschau.de", "https://www.tagesschau.de/"),
    "faz":     ("Frankfurter Allgemeine Zeitung", "https://www.faz.net/aktuell/politik/"),
    "sz":      ("Süddeutsche Zeitung", "https://www.sueddeutsche.de/politik"),
    "zeit":    ("Zeit Online", "https://www.zeit.de/politik/index"),
    "spiegel": ("Spiegel", "https://www.spiegel.de/politik/"),
    "hb":      ("Handelsblatt", "https://www.handelsblatt.com/politik/"),
    "taz":     ("TAZ", "https://taz.de/Politik/!p4615/"),
    "gn":      ("Google News", "https://news.google.com/?hl=de&gl=DE&ceid=DE%3Ade"),
}
ORDER = ["ts", "faz", "sz", "zeit", "spiegel", "hb", "taz", "gn"]

# Feeds je Medium mit Geltungsbereich ("scope"):
#   pol   = Politik allgemein (In- und Ausland gemischt)
#   world = Auslands-/Weltpolitik    de = Innenpolitik Deutschland
#   eu    = Europa                   wi = Wirtschaft
#   regio = Regionalnachrichten     mix = gemischte Schlagzeilen
# Adressen am 04.08.2026 über Feed-Verzeichnisse bzw. Live-Abruf verifiziert;
# scheitert eine Adresse dauerhaft, meldet data/meta.json den HTTP-Status.
FEEDS = {
    "ts": [
        ("https://www.tagesschau.de/ausland/index~rss2.xml", "world"),
        ("https://www.tagesschau.de/inland/innenpolitik/index~rss2.xml", "de"),
        ("https://www.tagesschau.de/wirtschaft/index~rss2.xml", "wi"),
        ("https://www.tagesschau.de/ausland/europa/index~rss2.xml", "eu"),
        ("https://www.tagesschau.de/inland/regional/index~rss2.xml", "regio"),
    ],
    "faz": [
        ("https://www.faz.net/rss/aktuell/politik/", "pol"),
        ("https://www.faz.net/rss/aktuell/politik/inland/", "de"),
        ("https://www.faz.net/rss/aktuell/wirtschaft/", "wi"),
    ],
    "sz": [
        ("https://rss.sueddeutsche.de/rss/Politik", "pol"),
        ("https://rss.sueddeutsche.de/rss/Wirtschaft", "wi"),
    ],
    "zeit": [
        ("https://newsfeed.zeit.de/politik/index", "pol"),
        ("https://newsfeed.zeit.de/wirtschaft/index", "wi"),
    ],
    "spiegel": [
        ("https://www.spiegel.de/politik/index.rss", "pol"),
        ("https://www.spiegel.de/wirtschaft/index.rss", "wi"),
    ],
    "hb": [
        ("https://feeds.cms.handelsblatt.com/politik", "pol"),
        ("https://feeds.cms.handelsblatt.com/unternehmen", "wi"),
        ("https://feeds.cms.handelsblatt.com/finanzen", "wi"),
    ],
    "taz": [
        ("https://taz.de/Politik/!p4615;rss/", "pol"),
        ("https://taz.de/Oeko/!p4610;rss/", "wi"),
    ],
}

# ------------------------------------------------------------ Bundesländer -

LAENDER = {
    "BW": ("Baden-Württemberg", "Stuttgart",
           ["Baden-Württemberg", "baden-württembergisch", "Stuttgart", "Karlsruhe",
            "Mannheim", "Freiburg", "Heidelberg", "Ulm"]),
    "BY": ("Bayern", "München",
           ["Bayern", "bayerisch", "bayrisch", "München", "Nürnberg", "Augsburg",
            "Regensburg", "Würzburg", "Söder"]),
    "BE": ("Berlin", "Berlin",
           ["Berlin", "Berliner Senat", "Abgeordnetenhaus", "Kreuzberg", "Neukölln",
            "Charlottenburg", "Pankow", "Spandau"]),
    "BB": ("Brandenburg", "Potsdam",
           ["Brandenburg", "brandenburgisch", "Potsdam", "Cottbus", "Frankfurt (Oder)",
            "Lausitz", "Oranienburg"]),
    "HB": ("Bremen", "Bremen",
           ["Bremen", "Bremerhaven", "Bürgerschaft", "Hansestadt Bremen"]),
    "HH": ("Hamburg", "Hamburg",
           ["Hamburg", "Hamburger Senat", "Hamburgische Bürgerschaft", "Elbphilharmonie",
            "Altona", "HafenCity"]),
    "HE": ("Hessen", "Wiesbaden",
           ["Hessen", "hessisch", "Wiesbaden", "Frankfurt", "Kassel", "Darmstadt",
            "Offenbach", "Gießen", "Fulda", "Marburg"]),
    "MV": ("Mecklenburg-Vorpommern", "Schwerin",
           ["Mecklenburg-Vorpommern", "Mecklenburg", "Vorpommern", "Schwerin",
            "Rostock", "Stralsund", "Greifswald", "Neubrandenburg"]),
    "NI": ("Niedersachsen", "Hannover",
           ["Niedersachsen", "niedersächsisch", "Hannover", "Braunschweig", "Osnabrück",
            "Oldenburg", "Göttingen", "Wolfsburg"]),
    "NW": ("Nordrhein-Westfalen", "Düsseldorf",
           ["Nordrhein-Westfalen", "NRW", "Düsseldorf", "Köln", "Dortmund", "Essen",
            "Duisburg", "Bochum", "Münster", "Aachen", "Wüst"]),
    "RP": ("Rheinland-Pfalz", "Mainz",
           ["Rheinland-Pfalz", "rheinland-pfälzisch", "Mainz", "Ludwigshafen",
            "Koblenz", "Trier", "Kaiserslautern"]),
    "SL": ("Saarland", "Saarbrücken",
           ["Saarland", "saarländisch", "Saarbrücken", "Neunkirchen", "Völklingen"]),
    "SN": ("Sachsen", "Dresden",
           ["Sachsen", "sächsisch", "Dresden", "Leipzig", "Chemnitz", "Zwickau",
            "Görlitz", "Kretschmer"]),
    "ST": ("Sachsen-Anhalt", "Magdeburg",
           ["Sachsen-Anhalt", "Magdeburg", "Halle", "Dessau", "Wittenberg", "Stendal"]),
    "SH": ("Schleswig-Holstein", "Kiel",
           ["Schleswig-Holstein", "schleswig-holsteinisch", "Kiel", "Lübeck",
            "Flensburg", "Neumünster", "Sylt"]),
    "TH": ("Thüringen", "Erfurt",
           ["Thüringen", "thüringisch", "Erfurt", "Jena", "Gera", "Weimar",
            "Eisenach", "Voigt"]),
}

# --------------------------------------------------------- Schlüsselwörter -

EU_WORDS = [
    "EU", "Europa", "europäisch", "Europäische Union", "EU-Kommission", "Brüssel",
    "Europaparlament", "EU-Parlament", "Europäisches Parlament", "EuGH", "EZB",
    "Eurozone", "Euroraum", "Binnenmarkt", "EU-Gipfel", "Frankreich", "Italien",
    "Spanien", "Polen", "Österreich", "Niederlande", "Belgien", "Schweden",
    "Dänemark", "Finnland", "Portugal", "Griechenland", "Ungarn", "Tschechien",
    "Slowakei", "Slowenien", "Rumänien", "Bulgarien", "Kroatien", "Irland",
    "Luxemburg", "Estland", "Lettland", "Litauen", "Malta", "Zypern",
    "Großbritannien", "Vereinigtes Königreich", "Schweiz", "Norwegen", "Ukraine",
    "Paris", "Rom", "Madrid", "Warschau", "Wien", "London", "Kiew", "Nato-Ostflanke",
]
DE_WORDS = [
    "Deutschland", "deutsche", "deutscher", "deutschen", "deutsches", "Bundestag",
    "Bundesrat", "Bundesregierung", "Bundeskanzler", "Bundeskanzlerin", "Kanzler",
    "Kanzlerin", "Bundesminister", "Bundesministerin", "Bundesministerium",
    "Bundeskabinett", "Kabinett", "Koalition", "Ampel", "CDU", "CSU", "SPD",
    "Grüne", "Grünen", "FDP", "AfD", "Linke", "Linkspartei", "BSW", "Bundeswehr",
    "Bundeshaushalt", "Bürgergeld", "Rente", "Landtag", "Ministerpräsident",
    "Ministerpräsidentin", "Bundesverfassungsgericht", "Karlsruhe", "Berlin",
    "Bundespolizei", "Wahlrecht", "Gesetzentwurf", "Bundesbank", "Mindestlohn",
]

def word_re(words):
    """Wortgrenzen-Muster, damit z. B. 'EU' nicht in 'neu' oder 'heute' zündet."""
    alts = sorted((re.escape(w) for w in words), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-zÄÖÜäöüß])(?:" + "|".join(alts) + r")(?![a-zäöüß])",
                      re.IGNORECASE)

EU_RE = word_re(EU_WORDS)
DE_RE = word_re(DE_WORDS)
LAND_RE = {code: word_re(words) for code, (_, _, words) in LAENDER.items()}

# --------------------------------------------------------------- Abrufen ---

def http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "de",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()

def fetch(url):
    """Zwei Versuche; Rückgabe (bytes|None, Statustext)."""
    last = "?"
    for attempt in (1, 2):
        try:
            return http_get(url), "ok"
        except Exception as e:  # HTTPError, URLError, Timeout, TLS …
            last = f"{type(e).__name__}: {getattr(e, 'code', '') or e}"
    return None, last

# --------------------------------------------------------------- Parsen ----

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

def strip_html(s):
    s = html.unescape(s or "")
    s = TAG_RE.sub(" ", s)
    return WS_RE.sub(" ", s).strip()

def clip(s, n=SUMMARY_MAX):
    if len(s) <= n:
        return s
    cut = s[:n]
    dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:dot + 1] if dot > 60 else cut.rstrip() + " …").strip()

def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)      # RFC 822 (RSS)
    except Exception:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))  # ISO (Atom)
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)

def local(tag):
    return tag.rsplit("}", 1)[-1].lower()

def parse_feed(raw):
    """RSS 2.0, Atom und RDF → Liste von {t, s, u, d(atetime)}."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # BOM/Präambel-Reste wegschneiden und erneut versuchen
        txt = raw.decode("utf-8", "replace")
        i = txt.find("<")
        try:
            root = ET.fromstring(txt[i:])
        except ET.ParseError:
            return []
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        t = s = u = date = None
        source = None
        for c in el:
            n = local(c.tag)
            txt = (c.text or "").strip()
            if n == "title":
                t = strip_html(txt)
            elif n in ("description", "summary"):
                s = s or strip_html(txt)
            elif n == "encoded" and not s:          # content:encoded
                s = strip_html(txt)
            elif n == "content" and not s:          # Atom-Content
                s = strip_html("".join(c.itertext()))
            elif n == "link":
                u = u or txt or c.get("href")
            elif n in ("pubdate", "date", "updated", "published"):
                date = date or parse_date(txt)
            elif n == "source":
                source = strip_html(txt)
        if not t or not u:
            continue
        s = s or ""
        # Google News: Titel enthält " - Quelle", Beschreibung ist oft nur der
        # verlinkte Titel selbst → dann Quelle als Inhaltsangabe verwenden.
        if s == t or (s and t.startswith(s[:40]) and len(s) <= len(t) + 5):
            s = ""
        if source and (not s):
            s = f"Meldung bei {source} – Titel anklicken, um den Beitrag beim Medium zu lesen."
        if source and t.endswith(" - " + source):
            t = t[: -(len(source) + 3)].rstrip()
        items.append({"t": t, "s": clip(s), "u": u, "d": date})
    return items

# --------------------------------------------------------------- Google ----

def gn_url(query, when="1d"):
    q = urllib.parse.quote(f"{query} when:{when}")
    return f"https://news.google.com/rss/search?q={q}&hl=de&gl=DE&ceid=DE:de"

GN_QUERIES = {
    "global":      gn_url("Weltpolitik OR Weltwirtschaft"),
    "europa":      gn_url("EU OR Europapolitik OR EU-Wirtschaft"),
    "deutschland": gn_url("Bundespolitik OR Bundesregierung OR Bundestag"),
}

def gn_land(code):
    name = LAENDER[code][0]
    return gn_url(f'"{name}" (Landtag OR Landesregierung OR Landespolitik OR Wirtschaft)', "2d")

# ------------------------------------------------ Vorgeladene Kommune ------
# Die Kommunal-Rubrik ist grundsätzlich besucherabhängig (PLZ erst im Browser
# bekannt). Für die mit Abstand wahrscheinlichste PLZ wird sie hier trotzdem
# wie eine feste Rubrik vorberechnet; alle anderen PLZ laden weiterhin live.
KOMMUNE_PLZ = "34132"
KOMMUNE_ORT = "Kassel"

DOMAINS = {"ts": "tagesschau.de", "faz": "faz.net", "sz": "sueddeutsche.de",
           "zeit": "zeit.de", "spiegel": "spiegel.de", "hb": "handelsblatt.com",
           "taz": "taz.de"}

def kommune_queries():
    """(Quell-ID, Suchtext, Zeitfenster) – identisch zu den Live-Anfragen der Seite."""
    q = [("gn", f'"{KOMMUNE_ORT}" Kommunalpolitik OR Stadtrat OR Gemeinderat OR Rathaus', "7d")]
    for sid in ORDER:
        if sid == "gn":
            continue
        q.append((sid, f'"{KOMMUNE_ORT}" site:{DOMAINS[sid]}', "14d"))
    return q

def gn_search_url(query, when):
    qq = urllib.parse.quote(f"{query} when:{when}")
    return f"https://news.google.com/search?q={qq}&hl=de&gl=DE&ceid=DE%3Ade"

# ------------------------------------------------------------- Sortieren ---

def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = it["u"] or it["t"]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

def newest(items, n=MAX_ITEMS):
    far_past = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    items = sorted(items, key=lambda it: it["d"] or far_past, reverse=True)
    return items[:n]

def text_of(it):
    return f'{it["t"]} {it["s"]}'

def build_rubrics(pool):
    """pool: {mkey: [(scope, item), …]}  →  Rubrik → mkey → Itemliste."""
    rub = {"global": {}, "europa": {}, "deutschland": {}}
    for code in LAENDER:
        rub["land-" + code] = {}
    for mkey, entries in pool.items():
        every = [it for _, it in entries]
        rub["global"][mkey] = newest(dedupe(every))
        eu = [it for sc, it in entries
              if sc == "eu" or (sc in ("pol", "world", "wi", "mix") and EU_RE.search(text_of(it)))]
        rub["europa"][mkey] = newest(dedupe(eu))
        de = [it for sc, it in entries
              if sc == "de" or (sc in ("pol", "wi", "mix", "regio") and DE_RE.search(text_of(it)))]
        rub["deutschland"][mkey] = newest(dedupe(de))
        for code in LAENDER:
            lr = LAND_RE[code]
            hits = [it for sc, it in entries
                    if sc in ("pol", "wi", "mix", "regio", "de") and lr.search(text_of(it))]
            rub["land-" + code][mkey] = newest(dedupe(hits))
    return rub

# ------------------------------------------------------------- Ausgabe -----

def sum_prompt(rubrik, sources):
    """Material = die jeweils ersten drei Beiträge je Quelle (Erstansicht)."""
    lines, missing, count = [], [], 0
    for s in sources:
        items = s.get("items") or []
        if not items:
            missing.append(s["name"])
            continue
        for it in items[:3]:
            count += 1
            txt = (it.get("s") or "")[:200]
            lines.append("• " + s["name"] + " – " + it["t"] + ((": " + txt) if txt else ""))
    head = ('Du bist die Zusammenfassungsfunktion der Nachrichtenübersicht "Merricksblatt". '
            'Fasse ausschließlich die folgenden Titel und Inhaltsangaben zusammen – keine eigene '
            'Recherche, keine Bewertung, keine erfundenen Details. Schreibe auf Deutsch einen in '
            'sich geschlossenen, klar strukturierten Fließtext von 60 bis 100 Wörtern: beginne mit '
            'den wichtigsten politischen Entwicklungen, gehe dann zu den wirtschaftlichen Themen '
            'über und verbinde verwandte Meldungen mit Übergängen zu einem roten Faden, statt sie '
            'aufzuzählen. Keine Aufzählungszeichen, keine Überschriften, keine Quellenliste.')
    if missing:
        head += (' Erwähne in einem kurzen Schlusssatz, dass folgende Quellen keine Beiträge '
                 'lieferten: ' + ", ".join(missing) + '.')
    return head + "\n\nRubrik: " + rubrik + "\n\nBeiträge:\n" + "\n".join(lines), count

_sum_state = {"calls": 0, "blocked": False}

def _post_json(url, payload, headers, timeout=90):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def _extract_text(raw):
    """OpenAI-Format, Cloudflare-Format oder blanker Text."""
    try:
        j = json.loads(raw)
    except Exception:
        return raw.strip()
    if isinstance(j, dict):
        ch = j.get("choices")
        if ch:
            return ((ch[0].get("message") or {}).get("content") or "").strip()
        res = j.get("result")
        if isinstance(res, dict):
            return (res.get("response") or "").strip()
    return ""

def _cf_call(prompt):
    acc = (os.environ.get("CF_ACCOUNT_ID") or "").strip()
    tok = (os.environ.get("CF_API_TOKEN") or "").strip()
    if not acc or not tok:
        return None, "nicht konfiguriert"
    model = (os.environ.get("CF_AI_MODEL") or CF_MODEL_DEFAULT).strip()
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}"
    try:
        raw = _post_json(url, {"messages": [{"role": "user", "content": prompt}],
                               "max_tokens": 300, "temperature": 0.4},
                         {"Authorization": "Bearer " + tok,
                          "Content-Type": "application/json", "User-Agent": UA})
        time.sleep(2)
        txt = _extract_text(raw)
        return (txt, "ok") if len(txt) > 40 else (None, "leere Antwort")
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:
        return None, type(e).__name__

def _polli_call(prompt):
    try:
        raw = _post_json(POLLI_URL, {"model": "openai", "private": True,
                                     "referrer": "merricksblatt.janrickmer.de",
                                     "messages": [{"role": "user", "content": prompt}]},
                         {"Content-Type": "application/json", "User-Agent": UA})
        time.sleep(POLLI_PAUSE)
        txt = _extract_text(raw)
        if len(txt) > 40 and not txt.lstrip().startswith("<"):
            return txt, "ok"
        return None, "leere/unbrauchbare Antwort"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(30)                       # Drossel beruhigen, einmal nachfassen
            try:
                raw = _post_json(POLLI_URL, {"model": "openai", "private": True,
                                             "referrer": "merricksblatt.janrickmer.de",
                                             "messages": [{"role": "user", "content": prompt}]},
                                 {"Content-Type": "application/json", "User-Agent": UA})
                time.sleep(POLLI_PAUSE)
                txt = _extract_text(raw)
                if len(txt) > 40 and not txt.lstrip().startswith("<"):
                    return txt, "ok"
            except Exception:
                pass
        return None, "HTTP %s" % e.code
    except Exception as e:
        time.sleep(POLLI_PAUSE)
        return None, type(e).__name__

def ai_summarize(rubrik, sources):
    """Rückgabe: (text|None, basis, via, status)."""
    if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("MB_KI") != "1":
        return None, 0, None, "übersprungen: läuft nicht in GitHub Actions"
    if _sum_state["blocked"]:
        return None, 0, None, "übersprungen: KI-Wege in diesem Lauf erschöpft"
    if _sum_state["calls"] >= SUM_MAX_CALLS:
        return None, 0, None, "übersprungen: Obergrenze je Lauf erreicht"
    prompt, count = sum_prompt(rubrik, sources)
    if count == 0:
        return None, 0, None, "übersprungen: keine Beiträge"

    _sum_state["calls"] += 1
    txt, st_cf = _cf_call(prompt)
    if txt:
        return txt, count, "Cloudflare Workers AI", "ok (Cloudflare Workers AI)"

    _sum_state["calls"] += 1
    txt, st_po = _polli_call(prompt)
    if txt:
        return txt, count, "Pollinations.AI", "ok (Pollinations)"

    if st_po.startswith("HTTP 4") and st_po != "HTTP 429":
        _sum_state["blocked"] = True             # harter Fehler → Lauf nicht weiter belasten
    return None, 0, None, f"fehlgeschlagen: Cloudflare {st_cf} / Pollinations {st_po}"

def sum_due(prev, minutes, now):
    ki = (prev or {}).get("ki") or {}
    g = ki.get("generated")
    if not g:
        return True
    try:
        d = dt.datetime.fromisoformat(g)
    except Exception:
        return True
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return (now - d) >= dt.timedelta(minutes=minutes)

def iso(d):
    return d.isoformat(timespec="seconds") if d else None

def load_previous(fn):
    try:
        with open(os.path.join(DATA, fn), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def source_block(mkey, items, ok, prev):
    name, home = MEDIA[mkey]
    block = {"id": mkey, "name": name, "home": home, "stale": False,
             "items": [{"t": i["t"], "s": i["s"], "u": i["u"], "d": iso(i["d"])} for i in items]}
    if not ok:
        # Abruf fehlgeschlagen → alte Beiträge dieser Quelle weiterreichen.
        old = None
        if prev:
            old = next((s for s in prev.get("sources", []) if s.get("id") == mkey), None)
        if old and old.get("items"):
            block["items"] = old["items"]
            block["stale"] = True
        else:
            block["err"] = True
    return block

def write_json(fn, payload):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, fn), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

# ---------------------------------------------------------------- Haupt ----

def main():
    now = dt.datetime.now(dt.timezone.utc)
    status = {}

    jobs = []            # (kind, mkey/code, scope, url)
    for mkey, feeds in FEEDS.items():
        for url, scope in feeds:
            jobs.append(("feed", mkey, scope, url))
    for rk, url in GN_QUERIES.items():
        jobs.append(("gn", rk, "mix", url))
    for code in LAENDER:
        jobs.append(("gnland", code, "mix", gn_land(code)))
    for sid, q, when in kommune_queries():
        jobs.append(("kommune", sid, "mix", gn_url(q, when)))

    results = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch, url): (kind, key, scope, url)
                for kind, key, scope, url in jobs}
        for fut in cf.as_completed(futs):
            kind, key, scope, url = futs[fut]
            raw, st = fut.result()
            items = parse_feed(raw) if raw else []
            if raw and not items:
                st = "ok, aber 0 Beiträge erkannt"
            status[url] = f"{st} ({len(items)})"
            results[(kind, key, url)] = (scope, items)

    # Publisher-Pool: Medium → [(scope, item), …]
    pool = {mkey: [] for mkey in FEEDS}
    ok_media = {mkey: False for mkey in FEEDS}
    for (kind, key, url), (scope, items) in results.items():
        if kind == "feed":
            if items:
                ok_media[key] = True
            for it in items:
                pool[key].append((scope, it))

    rubrics = build_rubrics(pool)

    # Google-News-Kästen
    gn_items = {rk: [] for rk in GN_QUERIES}
    gn_land_items = {code: [] for code in LAENDER}
    kommune_items, kommune_ok = {}, {}
    for (kind, key, url), (_, items) in results.items():
        if kind == "gn":
            gn_items[key] = newest(dedupe(items))
        elif kind == "gnland":
            gn_land_items[key] = newest(dedupe(items))
        elif kind == "kommune":
            kommune_items[key] = newest(dedupe(items))
            kommune_ok[key] = status[url].startswith("ok")

    def write_kommune(fn):
        prev = load_previous(fn)
        sources = []
        for sid, q, when in kommune_queries():
            name, home = MEDIA[sid]
            block = {"id": sid, "name": name, "home": home,
                     "search": gn_search_url(q, when), "stale": False,
                     "items": [{"t": i["t"], "s": i["s"], "u": i["u"], "d": iso(i["d"])}
                               for i in kommune_items.get(sid, [])]}
            if sid == "gn":
                block["kicker"] = "Aggregiert · zuerst geladen"
            if not block["items"] and not kommune_ok.get(sid, False):
                old = None
                if prev:
                    old = next((s for s in prev.get("sources", []) if s.get("id") == sid), None)
                if old and old.get("items") and not old.get("err"):
                    block["items"] = old["items"]
                    block["stale"] = True
            sources.append(block)
        payload = {"updated": iso(now), "rubrik": KOMMUNE_ORT, "plz": KOMMUNE_PLZ,
                   "sources": sources}
        prev_ki = (prev or {}).get("ki")
        if sum_due(prev, SUM_LAND_MIN, now):
            txt, basis, via, st = ai_summarize(KOMMUNE_ORT, sources)
            if txt:
                payload["ki"] = {"text": txt, "generated": iso(now), "basis": basis, "via": via}
            elif prev_ki:
                payload["ki"] = prev_ki
            ki_status[fn] = st
        else:
            if prev_ki:
                payload["ki"] = prev_ki
            ki_status[fn] = "aktuell (kein Neuaufbau fällig)"
        write_json(fn, payload)

    ki_status = {}

    def write_rubric(fn, rubrik_name, per_media, gn_list, gn_ok, sum_minutes):
        prev = load_previous(fn)
        sources = []
        for mkey in ORDER:
            if mkey == "gn":
                sources.append(source_block("gn", gn_list, gn_ok, prev))
            else:
                items = per_media.get(mkey, [])
                sources.append(source_block(mkey, items, ok_media[mkey], prev))
        payload = {"updated": iso(now), "rubrik": rubrik_name, "sources": sources}
        prev_ki = (prev or {}).get("ki")
        if sum_due(prev, sum_minutes, now):
            txt, basis, via, st = ai_summarize(rubrik_name, sources)
            if txt:
                payload["ki"] = {"text": txt, "generated": iso(now), "basis": basis, "via": via}
            elif prev_ki:
                payload["ki"] = prev_ki           # alte Fassung behalten statt Lücke
            ki_status[fn] = st
        else:
            if prev_ki:
                payload["ki"] = prev_ki
            ki_status[fn] = "aktuell (kein Neuaufbau fällig)"
        write_json(fn, payload)

    write_rubric("global.json", "Globales", rubrics["global"],
                 gn_items["global"], bool(gn_items["global"]), SUM_MAIN_MIN)
    write_rubric("europa.json", "Europa", rubrics["europa"],
                 gn_items["europa"], bool(gn_items["europa"]), SUM_MAIN_MIN)
    write_rubric("deutschland.json", "Deutschland", rubrics["deutschland"],
                 gn_items["deutschland"], bool(gn_items["deutschland"]), SUM_MAIN_MIN)
    for code, (name, _, _) in LAENDER.items():
        write_rubric(f"land-{code.lower()}.json", name, rubrics["land-" + code],
                     gn_land_items[code], bool(gn_land_items[code]), SUM_LAND_MIN)
    write_kommune(f"kommune-{KOMMUNE_PLZ}.json")

    write_json("meta.json", {"generated": iso(now), "feeds": status,
                             "ki_zusammenfassungen": ki_status})

    ok = sum(1 for v in status.values() if v.startswith("ok"))
    print(f"[Merricksblatt] {ok}/{len(status)} Abrufe erfolgreich – {iso(now)}")
    made = sum(1 for v in ki_status.values() if v.startswith("ok"))
    print(f"[Merricksblatt] KI-Zusammenfassungen: {made} neu erzeugt, "
          f"{sum(1 for v in ki_status.values() if v.startswith('aktuell'))} noch aktuell, "
          f"{_sum_state['calls']} KI-Aufrufe")
    for fn, st in sorted(ki_status.items()):
        if not (st.startswith("ok") or st.startswith("aktuell")):
            print(f"  KI-HINWEIS  {fn}  →  {st}")
    for url, st in sorted(status.items()):
        if not st.startswith("ok"):
            print(f"  FEHLER  {url}  →  {st}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
