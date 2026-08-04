# Merricksblatt – Veröffentlichung & Betrieb

Alles Nötige liegt in diesem Paket. Die Seite selbst ist eine einzige, gut
lesbare Datei (`index.html`); daneben liegen nur die PLZ-Tabelle, das
Abrufskript und der Workflow.

```
merricksblatt/
├── index.html                    ← die komplette Webseite (Design + Logik)
├── CNAME                         ← enthält: merricksblatt.janrickmer.de
├── assets/
│   └── plz.js                    ← Offline-PLZ-Tabelle (9 857 PLZ → Ort, Land, Koordinaten)
├── data/                         ← wird vom Workflow automatisch befüllt
│   └── README.md
├── scripts/
│   └── fetch_feeds.py            ← holt die Feeds serverseitig (nur Python-Standardbibliothek)
├── .github/workflows/feeds.yml   ← Zeitplan: alle 30 Minuten
└── test/                         ← optionale Selbsttests (Node), fürs Repo unschädlich
```

---

## Veröffentlichen in 6 Schritten

1. **Repository anlegen** – auf github.com „New repository“, Name z. B.
   `merricksblatt`, Sichtbarkeit **Public** (Voraussetzung für kostenloses
   Pages + unbegrenzte Actions-Minuten). Ohne Häkchen bei README anlegen.

2. **Dateien hochladen** – ZIP entpacken und den *Inhalt* des Ordners per
   „uploading an existing file“ bzw. Drag-and-drop in das leere Repository
   ziehen. Wichtig: Die Ordnerstruktur muss erhalten bleiben, insbesondere
   `.github/workflows/feeds.yml`. Falls der Browser den versteckten
   `.github`-Ordner beim Ziehen verschluckt: die Datei notfalls über
   „Add file → Create new file“ anlegen, als Namen
   `.github/workflows/feeds.yml` eintippen und den Inhalt hineinkopieren.
   Standardbranch sollte `main` heißen (GitHub-Voreinstellung).

3. **Ersten Datenlauf starten** – Reiter **Actions** öffnen. Beim ersten Mal
   fragt GitHub einmalig, ob Workflows erlaubt werden sollen → bestätigen.
   Der Upload selbst löst den Lauf „Merricksblatt Feeds“ bereits aus
   (sonst: Workflow anklicken → „Run workflow“). Nach 1–2 Minuten liegt im
   Ordner `data/` ein Satz frischer JSON-Dateien; `data/meta.json` zeigt
   für **jede einzelne Feed-Adresse** den Abrufstatus – das ist zugleich
   die endgültige Live-Verifikation aller Quellen aus dem echten
   Produktionsnetz.

4. **GitHub Pages einschalten** – Settings → Pages → Source: **Deploy from a
   branch**, Branch `main`, Ordner `/ (root)`, Save. Im Feld „Custom
   domain“ erscheint durch die CNAME-Datei automatisch
   `merricksblatt.janrickmer.de`.

5. **DNS bei Strato** – wie bei den übrigen janrickmer.de-Subdomains: für
   die Subdomain `merricksblatt` einen **CNAME-Eintrag** auf
   `DEIN-GITHUB-BENUTZERNAME.github.io` setzen (ohne https://, ohne
   Repository-Namen). Bis der Eintrag greift, können Minuten bis wenige
   Stunden vergehen.

6. **HTTPS erzwingen** – sobald GitHub unter Settings → Pages „DNS check
   successful“ meldet, Häkchen bei **Enforce HTTPS** setzen. Fertig.

Ab jetzt läuft alles von allein: Der Workflow holt die Feeds halbstündlich,
committet nur bei Änderungen, und jeder dieser Commits zählt als
Repository-Aktivität – damit hält sich der Zeitplan selbst am Leben
(GitHub schaltet geplante Workflows sonst nach 60 Tagen ohne Commits ab).

---

## Was die Seite im Betrieb tut

* **Globales / Europa / Deutschland / Bundesland** laden ausschließlich die
  eigenen `data/*.json` – schnell und ohne fremde Proxys. Alle 16
  Bundesländer sind vorberechnet; der Tab zeigt automatisch das Land zur
  PLZ. Die Rubrik aktualisiert sich im offenen Browserfenster alle
  10 Minuten von selbst.
* **Kommunales** wird live im Browser über Google-News-Suchen geladen
  (Gemeinde kennt erst der Besucher), über eine Kette kostenloser
  CORS-Proxys (allorigins → codetabs → allorigins/get). Scheitert eine
  Quelle, gibt es „Erneut versuchen“ – und ganz unten immer den
  Google-News-Button als Netz.
* **PLZ**: erst Gerätestandort (Zuordnung über die eingebettete
  Koordinatentabelle, ganz ohne externen Geo-Dienst), sonst Eingabefeld;
  ungültige Eingaben → 34132. Die gewählte PLZ merkt sich der Browser
  (localStorage), die Pille unter dem Slogan bleibt anklickbar.
* **KI-Zusammenfassung**: fasst exakt die gerade angezeigten Titel und
  Inhaltsangaben zusammen. Reihenfolge: Pollinations.AI (schlüsselfrei,
  POST → GET → über Proxy); klappt keiner der drei Wege, springt eine
  **lokale Kurzfassung** im Browser ein – der Knopf liefert also immer ein
  Ergebnis. Die Fußnote weist ehrlich aus, welcher Weg es war.
* **Vorlesen**: Sprachausgabe des Browsers, Deutsch, Tempo 1,35 – Knopf
  wechselt zu „Vorlesen beenden“.
* **Lokale Vorschau**: `index.html` doppelt geklickt zeigt das komplette
  Layout; weil Browser lokalen Dateien das Nachladen von `data/` verbieten,
  erscheinen dort klar gekennzeichnete Beispieldaten. Die PLZ-Funktion
  läuft auch lokal vollständig.

## Ehrliche Grenzen

* FAZ, SZ und Handelsblatt verlinken teils auf Bezahlartikel – Titel und
  Teaser sind frei, der Volltext nicht immer.
* Google-News-Links führen über eine kurze Google-Weiterleitung zum Medium;
  die Trefferlisten je Medium können bei kleinen Gemeinden dünn sein – die
  Kästen sagen das dann offen, statt Fremdes aufzufüllen.
* GitHubs Zeitplan ist „best effort“: 5–30 Minuten Verzug sind normal und
  für eine Nachrichtenübersicht unerheblich.
* Zwei Handelsblatt-Zusatzfeeds (unternehmen/finanzen) und der
  Spiegel-Wirtschaftsfeed folgen dem üblichen Adressschema, ließen sich aus
  meiner Umgebung aber nicht final abrufen – `data/meta.json` des ersten
  Laufs zeigt es schwarz auf weiß; ein toter Zusatzfeed schadet nicht, die
  Politik-Feeds tragen die Rubrik.

## Später anpassen – wo was steht

| Änderung | Datei / Stelle |
|---|---|
| Feed-Adresse tauschen, Quelle ergänzen | `scripts/fetch_feeds.py` → `FEEDS` |
| Schlüsselwörter Europa/Deutschland/Länder | ebd. → `EU_WORDS`, `DE_WORDS`, `LAENDER` |
| Abrufrhythmus | `.github/workflows/feeds.yml` → `cron` |
| Vorlesetempo | `index.html` → `u.rate = 1.35` |
| Anzahl je Klick nachgeladener Beiträge | `index.html` → `cur.shown[key] += 3` |
| Google-News-Vorfilter je Rubrik | `index.html` → `TABS` (gnQ/gnFilter) |
| Farben/Abstände | `index.html` → `<style>` (Werte aus dem Design-Entwurf) |

Selbsttests (optional, lokal mit Node ≥ 18):
`python3 test/run_test.py` erzeugt Prüfdaten, `npm i jsdom` einmalig,
`node test/jsdom_test.js` spielt Laden, PLZ, Kommunales und KI-Fallback durch.

Quellenhinweis: PLZ-Zuordnung aus GeoNames-Daten (Paket
zauberware/postal-codes-json-xml-csv, Lizenz CC BY 4.0) – der Hinweis dazu
steht bereits im Seitenfuß.
