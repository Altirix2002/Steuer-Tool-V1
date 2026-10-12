"""Erzeugt die installierbare Web-App (PWA) im Ordner site/ aus der Vorlage und den JSON-Daten.

Starten: python build_web.py
Ergebnis in site/: index.html, manifest.webmanifest, sw.js, icons/*.png
Der Service Worker bekommt eine Cache-Version aus einem Hash des Inhalts: Aendert sich etwas,
aendert sich die Version, und installierte Apps holen sich die neue Fassung automatisch.
Optional fuer Versuche: python build_web.py test  baut web/vorlage-test.html -> web/steuer-tool-test.html
So kommen alle Steuerwerte immer aus denselben Dateien wie beim Python-Programm.

Schrift: Liegt web/schrift/archivo.woff2 im Projekt, wird sie direkt in die Seite
eingebettet. Dann braucht die Seite kein Internet, auch nicht fuer die Schrift.
Fehlt die Datei, laedt die Seite die Schrift wie bisher von Google Fonts.
Schrift Archivo, Lizenz SIL Open Font License 1.1 (web/schrift/OFL.txt).

Schrift holen (Binaerdateien liegen nicht im claude.ai-Projekt):
  npm pack @fontsource-variable/archivo
  tar xzf fontsource-variable-archivo-*.tgz
  Datei package/files/archivo-latin-wdth-normal.woff2 nach web/schrift/archivo.woff2 kopieren
  (enthaelt Breite 62-125 und Gewicht 100-900), package/LICENSE nach web/schrift/OFL.txt.
"""

import base64
import hashlib
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path

ORDNER = Path(__file__).parent
DATEN = ORDNER / "daten"
SCHRIFT = ORDNER / "web" / "schrift" / "archivo.woff2"
SITE = ORDNER / "site"

NAME = "Steuern Zürich"
FARBE = (0x02, 0x80, 0x90)  # #028090, wie --petrol in der Vorlage
HINTERGRUND = "#EEF3F2"      # wie --grund in der Vorlage (heller Modus)

ICONS = [  # Datei, Kantenlaenge, Vollflaeche (maskable/Apple) oder abgerundet
    ("icon-192.png", 192, False),
    ("icon-512.png", 512, False),
    ("icon-maskable-512.png", 512, True),
    ("apple-touch-icon.png", 180, True),
]

# Wird in index.html vor </head> eingefuegt.
HEAD_EXTRA = (
    '<link rel="manifest" href="manifest.webmanifest">\n'
    '<link rel="icon" type="image/png" sizes="192x192" href="icons/icon-192.png">\n'
    '<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">\n'
    '<meta name="mobile-web-app-capable" content="yes">\n'
    '<meta name="apple-mobile-web-app-capable" content="yes">\n'
    '<meta name="apple-mobile-web-app-title" content="Steuern ZH">\n'
)

# Wird in index.html vor </body> eingefuegt.
SW_REGISTRIEREN = """<script>
// Service Worker: Offline-Fassung und automatische Aktualisierung
if ("serviceWorker" in navigator && location.protocol !== "file:") {
  window.addEventListener("load", () => {
    const hatteWorker = !!navigator.serviceWorker.controller;
    let neuGeladen = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!hatteWorker || neuGeladen) return;
      const neuLaden = () => { neuGeladen = true; location.reload(); };
      const a = document.activeElement;
      if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) a.addEventListener("blur", neuLaden, { once: true });
      else neuLaden();
    });
    navigator.serviceWorker.register("sw.js", { updateViaCache: "none" }).then((reg) => {
      const pruefen = () => reg.update().catch(() => {});
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") pruefen(); });
      setInterval(pruefen, 60 * 60 * 1000);
    }).catch(() => {});
  });
}
</script>
"""

SERVICE_WORKER = """// Service Worker, erzeugt von build_web.py. Nicht von Hand aendern.
// Version: __VERSION__ (Hash des Inhalts, aendert sich mit jeder Aenderung der App)
const CACHE = "steuern-zh-__VERSION__";
const DATEIEN = __DATEIEN__;

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(DATEIEN.map((d) => new Request(d, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((namen) => Promise.all(namen.filter((n) => n.startsWith("steuern-zh-") && n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

// PDFs aus dem Teilen-Menue (Web Share Target): nur auf dem Geraet in IndexedDB ablegen, nichts wird hochgeladen
function dbOeffnen() {
  return new Promise((ok, fehler) => {
    const r = indexedDB.open("steuertool-pdf", 1);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains("pdf")) db.createObjectStore("pdf", { keyPath: "id" });
      if (!db.objectStoreNames.contains("eingang")) db.createObjectStore("eingang", { keyPath: "id" });
    };
    r.onsuccess = () => ok(r.result);
    r.onerror = () => fehler(r.error);
  });
}
async function teilenAnnehmen(req) {
  try {
    const fd = await req.formData();
    const dateien = fd.getAll("pdf").filter((f) => f && typeof f !== "string" && f.size > 0);
    const db = await dbOeffnen();
    await new Promise((ok, fehler) => {
      const t = db.transaction("eingang", "readwrite"), o = t.objectStore("eingang");
      dateien.forEach((f, i) => o.put({ id: Date.now().toString(36) + "-" + i + "-" + Math.random().toString(36).slice(2, 8), name: f.name || "Dokument.pdf", groesse: f.size, zeit: Date.now(), blob: f.slice(0, f.size, "application/pdf") }));
      t.oncomplete = ok; t.onerror = t.onabort = () => fehler(t.error);
    });
    db.close();
  } catch (err) { /* App zeigt dann einfach nichts an */ }
  return Response.redirect(new URL("./?geteilt=1", self.registration.scope).href, 303);
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method === "POST" && new URL(req.url).pathname === new URL("teilen", self.registration.scope).pathname) {
    e.respondWith(teilenAnnehmen(req));
    return;
  }
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  const istSeite = req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  if (istSeite) {
    // HTML: zuerst aus dem Netz (am Browser-Cache vorbei), nur ohne Netz aus dem Cache
    e.respondWith(
      fetch(req, { cache: "no-store" })
        .then((res) => {
          if (res.ok) { const kopie = res.clone(); caches.open(CACHE).then((c) => c.put("index.html", kopie)); }
          return res;
        })
        .catch(() => caches.match("index.html").then((r) => r || caches.match("./")))
    );
  } else {
    // Rest (Icons, Manifest): aus dem Cache, sonst Netz
    e.respondWith(caches.match(req).then((r) => r || fetch(req)));
  }
});
"""

GOOGLE_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,300..900&display=swap" rel="stylesheet">\n'
)


def schrift_einbetten(html):
    if not SCHRIFT.exists():
        print("Hinweis: web/schrift/archivo.woff2 fehlt, Schrift kommt von Google Fonts.")
        return html
    if GOOGLE_FONTS not in html:
        raise SystemExit("Google-Fonts-Zeilen in web/vorlage.html nicht gefunden")
    b64 = base64.b64encode(SCHRIFT.read_bytes()).decode("ascii")
    style = (
        "<style>\n"
        "/* Archivo (SIL Open Font License 1.1), eingebettet, damit die Seite offline gleich aussieht */\n"
        '@font-face { font-family: "Archivo"; font-style: normal; font-display: swap;\n'
        "  font-weight: 100 900; font-stretch: 62% 125%;\n"
        f'  src: url(data:font/woff2;base64,{b64}) format("woff2"); }}\n'
        "</style>\n"
    )
    return html.replace(GOOGLE_FONTS, style)


def _png(breite, hoehe, rgba):
    def chunk(typ, daten):
        c = struct.pack(">I", len(daten)) + typ + daten
        return c + struct.pack(">I", zlib.crc32(typ + daten) & 0xFFFFFFFF)
    zeilen = b"".join(b"\x00" + rgba[y * breite * 4:(y + 1) * breite * 4] for y in range(hoehe))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(zeilen, 9))
            + chunk(b"IEND", b""))


def _abstand_strecke(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def icon_png(kante, vollflaeche):
    """Zeichnet das Logo aus der Vorlage (32x32: Rundrechteck mit drei weissen Strichen).
    vollflaeche=True: ganze Flaeche petrol, Striche im sicheren Bereich (maskable / Apple)."""
    striche = [(9, 21.5, 23, 21.5), (9, 16, 18, 16), (9, 10.5, 23, 10.5)]
    if vollflaeche:
        mass = kante * 0.9 / 32  # Logo auf 90 % der Flaeche, Striche liegen mittig
        versatz = kante * 0.05
    else:
        mass = kante / 32
        versatz = 0.0
    radius, halbe_breite = 9 * mass, 1.3 * mass
    mitte = kante / 2
    daten = bytearray()
    for y in range(kante):
        py = y + 0.5
        for x in range(kante):
            px = x + 0.5
            if vollflaeche:
                deckung = 1.0
            else:
                qx, qy = abs(px - mitte) - (mitte - radius), abs(py - mitte) - (mitte - radius)
                sd = (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** 0.5 + min(max(qx, qy), 0) - radius
                deckung = max(0.0, min(1.0, 0.5 - sd))
            if deckung == 0.0:
                daten += b"\x00\x00\x00\x00"
                continue
            weiss = 0.0
            for ax, ay, bx, by in striche:
                d = _abstand_strecke(px, py, versatz + ax * mass, versatz + ay * mass,
                                     versatz + bx * mass, versatz + by * mass) - halbe_breite
                weiss = max(weiss, max(0.0, min(1.0, 0.5 - d)))
            r, g, b = (round(c + (255 - c) * weiss) for c in FARBE)
            daten += bytes((r, g, b, round(255 * deckung)))
    return _png(kante, kante, bytes(daten))


def manifest():
    return json.dumps({
        "name": NAME,
        "short_name": "Steuern ZH",
        "description": "Belege-Checkliste und Steuerschätzung für den Kanton Zürich",
        "lang": "de-CH",
        "start_url": "./",
        "scope": "./",
        "id": "./",
        "display": "standalone",
        "orientation": "portrait",
        "theme_color": "#028090",
        "background_color": HINTERGRUND,
        "share_target": {
            "action": "./teilen",
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {"files": [{"name": "pdf", "accept": ["application/pdf", ".pdf"]}]},
        },
        "icons": [
            {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }, ensure_ascii=False, indent=2) + "\n"


def site_bauen(html):
    """Schreibt site/ neu: index.html, Manifest, Icons, Service Worker mit Inhalts-Hash als Version."""
    if "</head>" not in html or "</body>" not in html:
        raise SystemExit("</head> oder </body> fehlt in der Vorlage")
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "icons").mkdir(parents=True)
    html = html.replace("</head>", HEAD_EXTRA + "</head>", 1)
    ende = html.rindex("</body>")
    html = html[:ende] + SW_REGISTRIEREN + html[ende:]
    (SITE / "index.html").write_text(html, encoding="utf-8")
    (SITE / "manifest.webmanifest").write_text(manifest(), encoding="utf-8")
    for datei, kante, voll in ICONS:
        (SITE / "icons" / datei).write_bytes(icon_png(kante, voll))
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    dateien = sorted(p.relative_to(SITE).as_posix() for p in SITE.rglob("*") if p.is_file())
    h = hashlib.sha256()
    for name in dateien:
        h.update(name.encode("utf-8") + b"\0" + (SITE / name).read_bytes() + b"\0")
    version = h.hexdigest()[:12]
    vorab = ["./"] + [d for d in dateien if d != ".nojekyll"]
    sw = SERVICE_WORKER.replace("__VERSION__", version).replace("__DATEIEN__", json.dumps(vorab))
    (SITE / "sw.js").write_text(sw, encoding="utf-8")
    return version


def main():
    # Ohne Angabe: web/vorlage.html -> site/ (PWA)
    # Mit Angabe, z.B. "python build_web.py test": web/vorlage-test.html -> web/steuer-tool-test.html
    zusatz = ("-" + sys.argv[1]) if len(sys.argv) > 1 else ""
    tarife = {}
    for pfad in sorted(DATEN.glob("tarife_*.json")):
        jahr = pfad.stem.split("_")[1]
        tarife[jahr] = json.loads(pfad.read_text(encoding="utf-8"))
    checkliste = json.loads((DATEN / "checkliste.json").read_text(encoding="utf-8"))

    daten = json.dumps({"tarife": tarife, "checkliste": checkliste}, ensure_ascii=False)
    vorlage = (ORDNER / "web" / f"vorlage{zusatz}.html").read_text(encoding="utf-8")
    if "/*__DATEN__*/null" not in vorlage:
        raise SystemExit(f"Platzhalter /*__DATEN__*/null fehlt in web/vorlage{zusatz}.html")
    html = schrift_einbetten(vorlage).replace("/*__DATEN__*/null", daten)

    if zusatz:  # Versuchsvariante: nur eine einzelne Datei, keine PWA
        ziel = ORDNER / "web" / f"steuer-tool{zusatz}.html"
        ziel.write_text(html, encoding="utf-8")
        print(f"Erstellt: {ziel} ({len(html) // 1024} KB, Jahre: {', '.join(tarife)})")
        return
    version = site_bauen(html)
    print(f"Erstellt: {SITE} (index.html {len(html) // 1024} KB, Jahre: {', '.join(tarife)}, Cache-Version {version})")


if __name__ == "__main__":
    main()
