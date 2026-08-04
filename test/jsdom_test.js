/* Merricksblatt – jsdom-Integrationstest (Node) */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const BUILD = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(BUILD, "index.html"), "utf-8");
const plzjs = fs.readFileSync(path.join(BUILD, "assets", "plz.js"), "utf-8");
const globalJson = JSON.parse(fs.readFileSync(path.join(BUILD, "data", "global.json"), "utf-8"));
const heJson = JSON.parse(fs.readFileSync(path.join(BUILD, "data", "land-he.json"), "utf-8"));

const gnXml = fs.readFileSync(path.join(__dirname, "fixtures", "gnews.xml"), "utf-8");

const vc = new VirtualConsole();
vc.on("jsdomError", e => { if (!/Could not load/.test(String(e))) console.error("JSDOM:", e.message); });

const dom = new JSDOM(html, {
  url: "https://merricksblatt.janrickmer.de/",
  runScripts: "outside-only",
  pretendToBeVisual: true,
  virtualConsole: vc,
});
const { window } = dom;
const calls = [];
let failAll = false;

window.fetch = function (url) {
  calls.push(String(url));
  const u = String(url);
  const respond = (body, json) => Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve(json !== undefined ? json : JSON.parse(body)),
    text: () => Promise.resolve(body),
  });
  if (failAll) return Promise.reject(new Error("offline (Test)"));
  if (u.includes("data/global.json"))      return respond(JSON.stringify(globalJson));
  if (u.includes("data/land-he.json"))     return respond(JSON.stringify(heJson));
  if (u.includes("data/"))                 return respond(JSON.stringify(globalJson));
  if (u.includes("allorigins") || u.includes("codetabs")) return respond(gnXml);
  if (u.includes("pollinations"))          return Promise.reject(new Error("KI offline (Test)"));
  return Promise.reject(new Error("unerwartete URL: " + u));
};
window.AbortController = window.AbortController || function () { return { abort(){}, signal:{} }; };
// Geolocation absichtlich NICHT vorhanden → Modal muss erscheinen
delete window.navigator.geolocation;

// Skripte ausführen wie im Browser
window.eval(plzjs);
const main = html.match(/<script>([\s\S]*?)<\/script>/)[1];
window.eval(main);

const $ = id => window.document.getElementById(id);
const q = sel => window.document.querySelector(sel);
const qa = sel => [...window.document.querySelectorAll(sel)];
const sleep = ms => new Promise(r => setTimeout(r, ms));
let failures = 0;
function check(name, cond, extra) {
  if (cond) console.log("  ✔ " + name);
  else { failures++; console.log("  ✘ " + name + (extra ? "  → " + extra : "")); }
}

(async () => {
  console.log("— Start & Kopf —");
  check("Datum gesetzt", /\d{4}/.test($("datum").textContent), $("datum").textContent);
  check("Ausgabe Nr. plausibel", +$("ausgabe").textContent > 100, $("ausgabe").textContent);
  check("5 Tabs", qa(".tab").length === 5);
  check("PLZ-Modal offen (keine Geolokalisierung)", !$("plzModal").classList.contains("hidden"));

  console.log("— PLZ übernehmen —");
  $("plzInput").value = "34132";
  $("plzSave").click();
  check("Modal zu", $("plzModal").classList.contains("hidden"));
  check("PLZ-Pille", $("plzLabel").textContent === "34132 Kassel", $("plzLabel").textContent);
  const labels = qa(".tab span:first-child").map(n => n.textContent);
  check("Tab „Bundesland“ heißt Hessen", labels[3] === "Hessen", labels.join("/"));
  check("Tab „Kommunales“ heißt Kassel", labels[4] === "Kassel", labels.join("/"));

  await sleep(60);
  console.log("— Rubrik Globales aus data/global.json —");
  check("Meta-Zeile mit 8 Quellen", /8 Quellen · aktualisiert/.test($("rubrikMeta").textContent), $("rubrikMeta").textContent);
  check("8 Quellkästen", qa(".srcbox").length === 8, qa(".srcbox").length);
  const firstBox = q(".srcbox");
  check("Erste Quelle Tagesschau", firstBox.querySelector("h3").textContent === "Tagesschau.de");
  check("3 Beiträge sichtbar", firstBox.querySelectorAll(".item").length === 3);
  const link = firstBox.querySelector(".item .title");
  check("Link neuer Tab", link.target === "_blank" && link.rel.includes("noopener"));
  check("Google-News-Button verlinkt Suche", $("gnBtn").href.includes("news.google.com/search"), $("gnBtn").href);

  console.log("— Drei weitere laden (Fixture hat nur 3 → Erschöpft-Zustand) —");
  const more = firstBox.querySelector(".morebtn, .morewrap a");
  check("Erschöpft: Verweis aufs Medium", /Mehr direkt bei/.test(firstBox.querySelector(".morewrap").textContent));

  console.log("— Bundesland-Tab —");
  qa(".tab")[3].click();
  await sleep(60);
  check("Rubrik-Überschrift Hessen", $("rubrik").textContent === "Hessen", $("rubrik").textContent);
  check("land-he.json geladen", calls.some(u => u.includes("data/land-he.json")));
  const heBoxes = qa(".srcbox");
  const heItems = heBoxes[0].querySelectorAll(".item").length;
  check("Hessen-Kasten mit gefiltertem Beitrag", heItems >= 1, heItems);
  check("Leere Quelle mit ehrlichem Hinweis", qa(".notebox").some ? qa(".notebox").length >= 1 : false, qa(".notebox").length);

  console.log("— Kommunales (Google News über Proxy) —");
  qa(".tab")[4].click();
  await sleep(150);
  check("Rubrik-Überschrift Kassel", $("rubrik").textContent === "Kassel");
  check("8 Kästen (GN zuerst)", qa(".srcbox").length === 8, qa(".srcbox").length);
  check("GN-Kasten ganz oben", q(".srcbox h3").textContent === "Google News");
  check("Kicker „Aggregiert · zuerst geladen“", /Aggregiert/.test(q(".srcbox .kicker").textContent), q(".srcbox .kicker").textContent);
  await sleep(400);
  const gnItems = q(".srcbox").querySelectorAll(".item");
  check("GN-Beiträge aus Proxy-XML gerendert", gnItems.length >= 1, gnItems.length);
  check("GN-Titel ohne Quellen-Suffix", gnItems.length && !/ - hessenschau/.test(gnItems[0].querySelector(".title").textContent));
  check("Proxy-Kette benutzt", calls.some(u => u.includes("allorigins") || u.includes("codetabs")));

  console.log("— KI-Zusammenfassung: Dienst offline → lokale Ersatzfassung —");
  $("kiStart").click();
  check("Busy-Anzeige", !$("kiBusy").classList.contains("hidden"));
  await sleep(600);
  check("Ergebnis sichtbar", !$("kiDone").classList.contains("hidden"));
  check("Absätze vorhanden", $("kiText").querySelectorAll("p").length >= 1, $("kiText").textContent.slice(0,80));
  check("Fußnote kennzeichnet lokale Fassung", /lokale Kurzfassung/.test($("kiFoot").textContent), $("kiFoot").textContent);
  check("Vorlese-Knopf beschriftet", $("speakBtn").textContent.includes("vorlesen"));

  console.log("— Ausfallszenario: data/ nicht erreichbar —");
  failAll = true;
  qa(".tab")[0].click();
  // Cache umgehen: neue Instanz nötig wäre sauberer; hier reicht der Cache-Treffer-Test
  await sleep(60);
  check("Cache hält die Rubrik am Leben", qa(".srcbox").length === 8, qa(".srcbox").length);

  console.log(failures ? ("\nFEHLGESCHLAGEN: " + failures) : "\nALLE PRÜFUNGEN BESTANDEN");
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error("Testlauf abgestürzt:", e); process.exit(2); });
