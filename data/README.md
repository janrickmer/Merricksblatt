# data/ – automatisch befüllt

Dieser Ordner wird vom GitHub-Actions-Workflow „Merricksblatt Feeds“
(.github/workflows/feeds.yml) halbstündlich mit fertigen JSON-Dateien
gefüllt (global.json, europa.json, deutschland.json, land-xx.json für alle
16 Bundesländer sowie meta.json mit dem Abrufstatus jeder Quelle).

Hier nichts von Hand ablegen – Änderungen würden beim nächsten Lauf
überschrieben.
