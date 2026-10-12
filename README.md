# Steuer-Tool Kanton Zürich

Eigene Weboberfläche für die Steuererklärung (Stadt Zürich, Steuerjahre 2025 bis 2027).
Das Tool **ersetzt die Steuererklärung nicht**. Eingereicht wird weiterhin über ZHprivateTax oder auf Papier.

## Was es kann

1. **Belege-Checkliste**: alle Unterlagen abhaken, Beträge und Notizen speichern, mit der Ziffer in der Steuererklärung
2. **Eintragen**: Übersicht nach Ziffer, damit du in ZHprivateTax weisst, wo was hingehört
3. **Steuerrechner**: Steuern schätzen (Bund, Kanton, Gemeinde, Kirche, Personalsteuer)
4. **Einkommen schätzen**: steuerbares Einkommen für Bund und Kanton aus Lohn und Belegen, je mit den eigenen Abzügen (inkl. Weiterbildung und Schuldzinsen, z.B. für ein Ausbildungsdarlehen)
5. **Säule 3a: was wäre wenn**: zeigt, wie viel Steuern eine Einzahlung spart
6. **Hilfe**: erklärt jedes Eingabefeld und wo du die Zahl findest
7. **Datenstatus**: zeigt, welche Steuerwerte geprüft sind, welche noch geprüft werden müssen und welche fehlen

## Weboberfläche (installierbare App)

Die App ist eine PWA und liegt auf GitHub Pages: **https://altirix2002.github.io/Steuer-Tool-V1/**

- **Installieren (Android, Chrome):** Seite öffnen, Menü ⋮ → «App installieren» bzw. «Zum Startbildschirm hinzufügen».
- **Aktualisieren:** automatisch. Jeder Push auf `main` startet die Tests, baut die Seite und veröffentlicht sie, wenn alle Tests bestehen. Die installierte App holt sich die neue Fassung beim nächsten Öffnen.
- **Offline:** funktioniert nach dem ersten Öffnen. Das HTML wird immer zuerst aus dem Netz geladen, nur ohne Netz aus dem Cache.

Gleiche Daten und gleiche Rechnung wie das Python-Programm. Eingaben bleiben nur im Browser auf dem Gerät. Unter «Info» kannst du sie als Datei sichern.

Lokal bauen und ansehen (erzeugt den Ordner `site/`, der nicht ins Repository kommt):

```
python build_web.py
python -m http.server -d site 8000
```

Dann `http://localhost:8000` öffnen. Der Service Worker läuft nur über `http://localhost` oder `https`, nicht über `file://`.

## Prüfprogramm (Python)

`rechner.py` ist eine zweite, unabhängige Rechnung in Python. Sie hat keine eigene Oberfläche, sondern dient zur Kontrolle: Die Tests prüfen sie gegen die amtlichen Tabellen, und die Weboberfläche muss auf den Rappen gleich rechnen. Python 3 genügt, keine Zusatzpakete.

```
python -m unittest discover tests
```

Bei neuen Rechenregeln (z.B. ein neuer Abzug) werden beide Rechnungen nachgeführt. Neue Tarife stehen nur in den JSON-Dateien.

## Ordner

| Datei | Inhalt |
|---|---|
| `rechner.py` | Prüfrechnung in Python (für die Tests) |
| `build_web.py` | Erzeugt die App in `site/` aus Vorlage und JSON-Daten |
| `web/vorlage.html` | Vorlage der Weboberfläche |
| `site/` | Fertige App mit Manifest, Service Worker und Icons (erzeugt, nicht im Repository) |
| `.github/workflows/pages.yml` | Tests, Bauen und Veröffentlichen bei jedem Push auf `main` |
| `daten/tarife_JJJJ.json` | Alle Steuerwerte eines Jahres mit Quelle und Status |
| `daten/checkliste.json` | Punkte der Checkliste mit Ziffern (kannst du erweitern) |
| `tests/` | Automatische Tests |

## Stand der Steuerdaten

| Teil | 2026 | 2027 | Quelle |
|---|---|---|---|
| Bundessteuer Tarif und Abzüge | geprüft | geprüft | ESTV Rundschreiben vom 11.09.2025 und 22.09.2026 |
| Tarife Kanton (Einkommen, Vermögen) | geprüft | geprüft | StG ZH §§ 35 und 47, Nachtrag 132; gilt für die Periode 2026/2027 |
| Abzüge Kanton | geprüft | geprüft | StG ZH §§ 26, 31, 32, 34 |
| Schuldzinsen (Vermögensertrag plus 50'000) | geprüft | geprüft | Art. 33 Abs. 1 lit. a DBG, StG ZH § 31 Abs. 1 lit. a |
| Pauschalen Berufsauslagen Kanton | geprüft | geprüft | Verfügung LS 631.33 (ab Steuerperiode 2026) |
| Staatssteuerfuss 95 % | geprüft | geprüft | zh.ch/steuerfuesse |
| Gemeindesteuerfuss Stadt Zürich 119 % | geprüft | **prüfen** | zh.ch/steuerfuesse (2027 erst Anfang 2027 bekannt) |
| Kirchensteuer ref. 10 %, kath. 10 %, christkath. 14 % | geprüft | **prüfen** | zh.ch/steuerfuesse |
| Personalsteuer CHF 24 | geprüft | geprüft | StG ZH § 200 |
| Säule 3a Maximum 7'258 (2026), 7'373 (2027) | geprüft | geprüft | BSV Medienmitteilung vom 02.10.2026 (Bundesratsbeschluss) |

**Steuerjahr 2025** (nur für den Vergleich mit der Steuererklärung 2025): Bundestarif geprüft (ESTV), Kantonstarif aus einer Tabelle des Regierungsrats (stimmt mit der Steuerberechnung 2025 überein). Vermögenstarif und Abzüge 2025 fehlen.

Fehlt ein Wert (Status «fehlt»), rechnet das Tool diesen Teil nicht, statt falsche Zahlen anzuzeigen.

## Jährliche Aktualisierung

Eine geplante Aufgabe läuft jedes Jahr am 1. Oktober: Sie sucht die neuen Werte bei ESTV und zh.ch, legt `daten/tarife_JJJJ.json` an, testet alles und meldet, was noch fehlt. Der Bund passt die Werte jedes Jahr an, der Kanton nur auf den Beginn einer zweijährigen Steuerfussperiode (nächstes Mal 2028).

## Wichtige Grenzen

- Ergebnis ist eine **Schätzung**. Verbindlich ist nur die Veranlagung des Steueramts.
- Die Ziffern für ZHprivateTax stammen aus dem Formular 2025. Für 2026 kurz kontrollieren.
- Nicht enthalten: Unterstützungsabzug, Zweiverdienerabzug, selbständiger Erwerb im Detail. Schuldzinsen sind auf 50'000 begrenzt, weil Vermögenserträge nicht erfasst werden.
- Nebenerwerb, Weiterbildungskosten und Krypto sind als «abklären» markiert. Das am besten beim Steueramt nachfragen.
- Annahme: Einkommen für die Bundessteuer wird auf 100 Franken abgerundet (so ist der Tarif aufgebaut).
- Der Test `TestVergleichSteuerberechnung2025` braucht persönliche Zahlen aus `tests/vergleich_2025.privat.json`. Diese Datei steht in `.gitignore` und wird nie hochgeladen. Ohne sie wird der Test übersprungen (Vorlage: `tests/vergleich_2025.beispiel.json`).
