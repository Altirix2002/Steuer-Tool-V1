"""Tests: Bundessteuer gegen die amtliche ESTV-Tabelle 2026 (Form. 58c, ESTV/DVS 01.2026).

Starten: python -m unittest discover tests
"""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import rechner  # noqa: E402

TARIFE = rechner.lade_tarife(2026)


class TestBundessteuer(unittest.TestCase):
    # (Einkommen, Steuer) aus der ESTV-Tabelle 2026
    ALLEINSTEHEND = [
        (15000, "0.00"), (20000, "36.96"), (36000, "163.24"), (43400, "228.36"),
        (57900, "609.36"), (90000, "2024.35"), (138300, "5858.95"),
        (148300, "6888.55"), (350000, "32703.35"), (794000, "91310.00"),
    ]
    VERHEIRATET = [
        (94900, "1561.00"), (138300, "4282.00"), (148300, "5221.00"),
        (350000, "31380.00"), (941400, "108261.00"),
    ]

    def test_alleinstehend(self):
        for einkommen, erwartet in self.ALLEINSTEHEND:
            with self.subTest(einkommen=einkommen):
                self.assertEqual(rechner.bundessteuer(einkommen, TARIFE), Decimal(erwartet))

    def test_verheiratet(self):
        for einkommen, erwartet in self.VERHEIRATET:
            with self.subTest(einkommen=einkommen):
                self.assertEqual(rechner.bundessteuer(einkommen, TARIFE, verheiratet=True), Decimal(erwartet))

    def test_unter_25_franken_wird_nicht_erhoben(self):
        # 15200 + 3000 -> 30 * 0.77 = 23.10 -> unter 25 -> 0
        self.assertEqual(rechner.bundessteuer(18200, TARIFE), Decimal("0.00"))

    def test_abrunden_auf_100(self):
        self.assertEqual(rechner.bundessteuer(36099, TARIFE), rechner.bundessteuer(36000, TARIFE))


class TestKanton(unittest.TestCase):
    def test_fehlender_tarif_wird_nicht_berechnet(self):
        import copy
        ohne = copy.deepcopy(TARIFE)
        ohne["kanton_zh"]["einkommenssteuer_grundtarif"]["status"] = "fehlt"
        res = rechner.berechne({"einkommen_bund": 50000, "einkommen_kanton": 50000}, ohne)
        self.assertTrue(res["fehlt"])
        self.assertNotIn("Staatssteuer (95%)", res["teile"])

    def test_tarifgrenzen_wie_im_gesetz(self):
        # Summe der Stufen muss der Grenze der letzten Stufe im Gesetz entsprechen (StG ZH 35, 47)
        zh = TARIFE["kanton_zh"]
        for name, grenze in [("einkommenssteuer_grundtarif", 266700),
                             ("einkommenssteuer_verheiratetentarif", 370600),
                             ("vermoegenssteuer_grundtarif", 3304000),
                             ("vermoegenssteuer_verheiratetentarif", 3385000)]:
            with self.subTest(name=name):
                self.assertEqual(sum(s["betrag"] for s in zh[name]["stufen"] if s["betrag"]), grenze)

    def test_einfache_staatssteuer_von_hand_gerechnet(self):
        # 50'000 Grundtarif: 0 + 100 + 144 + 320 + 485 + 672 + 4'300*7% (301) = 2'022
        self.assertEqual(rechner.einfache_staatssteuer_einkommen(50000, TARIFE), Decimal("2022.00"))
        # 300'000: ueber 266'700 gilt 13%
        bis_grenze = rechner.einfache_staatssteuer_einkommen(266700, TARIFE)
        self.assertEqual(rechner.einfache_staatssteuer_einkommen(300000, TARIFE),
                         bis_grenze + Decimal("33300") * Decimal("0.13"))

    def test_vermoegen_unter_freibetrag(self):
        self.assertEqual(rechner.einfache_staatssteuer_vermoegen(81000, TARIFE), Decimal("0.00"))
        self.assertEqual(rechner.einfache_staatssteuer_vermoegen(100000, TARIFE), Decimal("9.50"))

    def test_gesamt_stadt_zuerich(self):
        res = rechner.berechne({"einkommen_bund": 50000, "einkommen_kanton": 50000}, TARIFE)
        self.assertEqual(res["teile"]["Staatssteuer (95%)"], Decimal("1920.90"))
        self.assertEqual(res["teile"]["Gemeindesteuer (119%)"], Decimal("2406.18"))
        self.assertEqual(res["teile"]["Personalsteuer"], Decimal("24.00"))
        self.assertFalse(res["fehlt"])

    def test_stufentarif_mechanik(self):
        # Fiktiver Tarif, nur um die Rechenlogik zu pruefen (keine echten Werte!)
        stufen = [{"satz_prozent": 0, "betrag": 1000},
                  {"satz_prozent": 10, "betrag": 1000},
                  {"satz_prozent": 20, "betrag": None}]
        self.assertEqual(rechner._progressiv(500, stufen, "satz_prozent", 100), Decimal("0.00"))
        self.assertEqual(rechner._progressiv(1500, stufen, "satz_prozent", 100), Decimal("50.00"))
        self.assertEqual(rechner._progressiv(3000, stufen, "satz_prozent", 100), Decimal("300.00"))


class TestVergleichSteuerberechnung2025(unittest.TestCase):
    """Vergleich mit einer echten Steuerberechnung 2025 (Software Dr. Tax ZH, provisorisch).
    Die Zahlen sind persoenlich und stehen in tests/vergleich_2025.privat.json (nicht im Repository).
    Fehlt die Datei, wird der Test uebersprungen. Aufbau: tests/vergleich_2025.beispiel.json.
    Kleine Differenzen kommen von Rundungen der Software."""

    PRIVAT = Path(__file__).parent / "vergleich_2025.privat.json"

    @unittest.skipUnless(PRIVAT.exists(), "tests/vergleich_2025.privat.json fehlt (persoenliche Zahlen)")
    def test_vergleich(self):
        import json
        d = json.loads(self.PRIVAT.read_text(encoding="utf-8"))
        t = rechner.lade_tarife(2025)
        res = rechner.berechne({"einkommen_bund": d["einkommen_bund"], "einkommen_kanton": d["einkommen_kanton"]}, t)
        for name, wert in d["erwartet"].items():
            with self.subTest(name=name):
                self.assertLessEqual(abs(res["teile"][name] - Decimal(wert)), Decimal("1.00"))
        name = "Einfache Staatssteuer (Basis)"
        self.assertEqual(res["teile"][name], Decimal(d["erwartet"][name]))


class TestFristen(unittest.TestCase):
    """Fristen laut Zuercher Steuerbuch ZStB-Nr. 132.3 (Einreichung 31.03. des Folgejahres)."""

    def test_daten_pro_jahr(self):
        from datetime import date
        for jahr in (2025, 2026, 2027):
            with self.subTest(jahr=jahr):
                f = rechner.lade_tarife(jahr)["fristen"]
                e, x = f["einreichefrist"], f["fristerstreckung_max_ohne_begruendung"]
                self.assertEqual(date.fromisoformat(e["datum"]), date(jahr + 1, 3, 31))
                self.assertEqual(date.fromisoformat(x["datum"]), date(jahr + 1, 11, 30))
                self.assertEqual(e["status"], "verifiziert")
                self.assertEqual(x["status"], "zu_pruefen")
                self.assertTrue(e["_quelle"] and x["_quelle"])
                self.assertGreater(x["datum"], e["datum"])

    def test_stufen(self):
        from datetime import date
        t = rechner.lade_tarife(2026)   # Frist 31.03.2027
        frist = date(2027, 3, 31)
        from datetime import timedelta
        for tage, stufe in [(200, "normal"), (31, "normal"), (30, "bald"), (8, "bald"), (7, "dringend"), (0, "dringend"), (-3, "dringend")]:
            with self.subTest(tage=tage):
                info = rechner.frist_info(t, frist - timedelta(days=tage))
                self.assertEqual(info["tage"], tage)
                self.assertEqual(info["stufe"], stufe)

    def test_eigene_frist_gilt_statt_standard(self):
        from datetime import date
        t = rechner.lade_tarife(2026)
        info = rechner.frist_info(t, date(2027, 3, 1), eigene="2027-04-30")
        self.assertEqual(info["frist"], date(2027, 4, 30))
        self.assertEqual(info["tage"], 60)
        self.assertTrue(info["eigene"])
        self.assertFalse(rechner.frist_info(t, date(2027, 3, 1))["eigene"])

    def test_ohne_fristen_keine_info(self):
        from datetime import date
        self.assertIsNone(rechner.frist_info({}, date(2027, 3, 1)))


class TestZuruecklegen(unittest.TestCase):
    def test_pro_monat_und_rest(self):
        from datetime import date
        # Oktober 2026: Oktober, November, Dezember = 3 Monate
        r = rechner.zuruecklegen(Decimal("2400"), Decimal("600"), 2026, date(2026, 10, 12))
        self.assertEqual(r["pro_monat"], Decimal("200.00"))
        self.assertEqual(r["fehlt"], Decimal("1800.00"))
        self.assertEqual(r["monate"], 3)
        self.assertEqual(r["pro_monat_bis_ende"], Decimal("600.00"))
        self.assertEqual(r["ueberschuss"], Decimal("0.00"))

    def test_monate(self):
        from datetime import date
        self.assertEqual(rechner.monate_bis_jahresende(2026, date(2026, 1, 31)), 12)
        self.assertEqual(rechner.monate_bis_jahresende(2026, date(2026, 12, 31)), 1)
        self.assertEqual(rechner.monate_bis_jahresende(2027, date(2026, 10, 12)), 12)
        self.assertEqual(rechner.monate_bis_jahresende(2025, date(2026, 10, 12)), 0)

    def test_genug_zurueckgelegt(self):
        from datetime import date
        r = rechner.zuruecklegen(Decimal("1000"), Decimal("1200"), 2026, date(2026, 3, 1))
        self.assertEqual(r["fehlt"], Decimal("0.00"))
        self.assertEqual(r["ueberschuss"], Decimal("200.00"))
        self.assertEqual(r["pro_monat_bis_ende"], Decimal("0.00"))

    def test_jahr_vorbei(self):
        from datetime import date
        r = rechner.zuruecklegen(Decimal("1000"), Decimal("400"), 2025, date(2026, 3, 1))
        self.assertEqual(r["fehlt"], Decimal("600.00"))
        self.assertIsNone(r["pro_monat_bis_ende"])

    def test_rundung_auf_rappen(self):
        from datetime import date
        r = rechner.zuruecklegen(Decimal("1000"), Decimal("0"), 2027, date(2026, 10, 12))
        self.assertEqual(r["pro_monat"], Decimal("83.33"))


class TestSicherungErinnerung(unittest.TestCase):
    def test_faelligkeit(self):
        from datetime import datetime, timedelta
        jetzt = datetime(2026, 10, 12, 12, 0)
        self.assertFalse(rechner.sicherung_faellig(jetzt - timedelta(days=30), jetzt, True))
        self.assertTrue(rechner.sicherung_faellig(jetzt - timedelta(days=31), jetzt, True))
        self.assertFalse(rechner.sicherung_faellig(jetzt - timedelta(days=1), jetzt, True))

    def test_noch_nie_gesichert(self):
        from datetime import datetime
        jetzt = datetime(2026, 10, 12)
        self.assertTrue(rechner.sicherung_faellig(None, jetzt, True))
        self.assertFalse(rechner.sicherung_faellig(None, jetzt, False))


class TestJahr2027(unittest.TestCase):
    """Bundestarif 2027 gegen die Stufen im ESTV Rundschreiben 2-220-D-2026."""
    def test_stufen(self):
        t = rechner.lade_tarife(2027)
        for eink, erwartet in [(15300, "0.00"), (33400, "139.35"), (109400, "3288.30"), (185900, "10981.70"), (797500, "91712.50")]:
            with self.subTest(eink=eink):
                self.assertEqual(rechner.bundessteuer(eink, t), Decimal(erwartet))
        for eink, erwartet in [(53700, "238.00"), (153100, "5714.00"), (946000, "108790.00")]:
            with self.subTest(eink=eink):
                self.assertEqual(rechner.bundessteuer(eink, t, verheiratet=True), Decimal(erwartet))

    def test_stufen_lueckenlos(self):
        # Jede Stufe muss aus der vorherigen folgen (Tippfehler-Kontrolle), Toleranz 5 Rappen
        t = rechner.lade_tarife(2027)
        for name in ["tarif_alleinstehend", "tarif_verheiratet"]:
            s = t["bund"][name]["stufen"]
            for a, b in zip(s[:-2], s[1:-1]):
                berechnet = Decimal(str(a["basis"])) + (b["ab"] - a["ab"]) // 100 * Decimal(str(a["satz_pro_100"]))
                with self.subTest(name=name, ab=b["ab"]):
                    self.assertLessEqual(abs(berechnet - Decimal(str(b["basis"]))), Decimal("0.05"))


class TestSaeule3a(unittest.TestCase):
    """Maximalbetraege laut BSV Medienmitteilung vom 02.10.2026 (Bundesratsbeschluss)."""
    def test_werte(self):
        for jahr, mit, ohne in [(2026, 7258, 36288), (2027, 7373, 36864)]:
            with self.subTest(jahr=jahr):
                v = rechner.lade_tarife(jahr)["saeule_3a"]
                self.assertEqual(v["max_mit_pensionskasse"], mit)
                self.assertEqual(v["max_ohne_pensionskasse"], ohne)
                self.assertEqual(v["ohne_pensionskasse_prozent_vom_erwerbseinkommen"], 20)
                self.assertEqual(v["status"], "verifiziert")


class TestEinkommenAusAngaben(unittest.TestCase):
    ANG = dict(netto=60000, fahr=900, verpf=3200, pk=True, s3a=7258, kk=4000, krankheit=3000, spenden=500)

    def test_bund(self):
        t = rechner.lade_tarife(2026)
        total, _ = rechner.einkommen_aus_angaben(self.ANG, t, "bund")
        # 60000 - 900 - 3200 - 2000 (3% = 1800 -> Minimum 2000) - 7258 - 1800 = 44842
        # Krankheit: 3000 - 5% von 44842 (2242.10) = 757.90 ; Spenden 500
        self.assertEqual(total, Decimal("43584.10"))

    def test_kanton_ohne_pauschalen(self):
        t = rechner.lade_tarife(2026)
        if t["kanton_zh"]["abzuege"]["berufskosten_pauschalen"]["status"] == "fehlt":
            with self.assertRaises(rechner.FehlendeDaten):
                rechner.einkommen_aus_angaben(self.ANG, t, "kanton")

    def test_kanton_mechanik(self):
        # Fiktive Pauschalen, nur um die Rechenlogik zu pruefen (keine echten Werte!)
        import copy
        t = copy.deepcopy(rechner.lade_tarife(2026))
        t["kanton_zh"]["abzuege"]["berufskosten_pauschalen"] = {
            "status": "verifiziert", "verpflegung_voll_pro_jahr": 3200,
            "uebrige_berufskosten_prozent": 3, "uebrige_berufskosten_min": 2000, "uebrige_berufskosten_max": 4000}
        total, _ = rechner.einkommen_aus_angaben(dict(self.ANG, kinder=1), t, "kanton")
        # 60000 - 900 - 3200 - 2000 - 7258 - 4000 (max 2900 + 1300 Kind) = 42642
        # Krankheit 3000 - 2132.10 = 867.90 ; Spenden 500 ; Kinderabzug 9400
        self.assertEqual(total, Decimal("31874.10"))


class TestSchuldzinsen(unittest.TestCase):
    """Art. 33 Abs. 1 lit. a DBG / Paragraph 31 Abs. 1 lit. a StG ZH."""
    ANG = dict(netto=60000, fahr=900, verpf=3200, pk=True, s3a=7258, kk=4000, krankheit=3000, spenden=500)

    def test_zinsen_senken_nettoeinkommen(self):
        t = rechner.lade_tarife(2026)
        total, zeilen = rechner.einkommen_aus_angaben(dict(self.ANG, zinsen=150), t, "bund")
        # Nettoeinkommen 44842 - 150 = 44692 ; Krankheit 3000 - 2234.60 = 765.40 ; Spenden 500
        self.assertEqual(total, Decimal("43426.60"))
        self.assertIn(("Private Schuldzinsen", Decimal("-150")), zeilen)

    def test_zinsen_kanton(self):
        t = rechner.lade_tarife(2026)
        ohne, _ = rechner.einkommen_aus_angaben(self.ANG, t, "kanton")
        mit, _ = rechner.einkommen_aus_angaben(dict(self.ANG, zinsen=150), t, "kanton")
        self.assertLess(mit, ohne)

    def test_obergrenze_50000(self):
        t = rechner.lade_tarife(2026)
        _, zeilen = rechner.einkommen_aus_angaben(dict(self.ANG, netto=200000, zinsen=80000), t, "bund")
        self.assertIn(("Private Schuldzinsen", Decimal("-50000")), zeilen)

    def test_grenze_fehlt(self):
        import copy
        t = copy.deepcopy(rechner.lade_tarife(2026))
        del t["bund"]["abzuege"]["schuldzinsen_max_ohne_vermoegensertrag"]
        with self.assertRaises(rechner.FehlendeDaten):
            rechner.einkommen_aus_angaben(dict(self.ANG, zinsen=150), t, "bund")


class TestErsparnis3a(unittest.TestCase):
    def test_ersparnis(self):
        t = rechner.lade_tarife(2026)
        e = {"einkommen_bund": 50000, "einkommen_kanton": 50000}
        vorher = rechner.berechne(e, t)["total"]
        nachher = rechner.berechne({"einkommen_bund": 50000 - 7258, "einkommen_kanton": 50000 - 7258}, t)["total"]
        self.assertEqual(rechner.ersparnis_3a(e, t, 7258), vorher - nachher)
        self.assertGreater(rechner.ersparnis_3a(e, t, 7258), 0)


class TestZiffern(unittest.TestCase):
    def test_wichtige_belege_haben_ziffer(self):
        import json
        d = json.loads((Path(__file__).parent.parent / "daten" / "checkliste.json").read_text(encoding="utf-8"))
        ziffern = {p["id"]: p.get("ziffer") for k in d["kategorien"] for p in k["punkte"]}
        for pid, z in [("lohnausweis", "1.1"), ("saeule3a", "14.1"), ("krankenkasse", "15"), ("spenden", "22.2"),
                       ("schuldzinsen", "12"), ("schulden", "34")]:
            self.assertEqual(ziffern[pid], z)


class TestAbzuege(unittest.TestCase):
    def test_berufskosten_pauschale(self):
        self.assertEqual(rechner.berufskosten_pauschale_bund(40000, TARIFE), Decimal("2000.00"))   # Minimum
        self.assertEqual(rechner.berufskosten_pauschale_bund(100000, TARIFE), Decimal("3000.00"))  # 3%
        self.assertEqual(rechner.berufskosten_pauschale_bund(200000, TARIFE), Decimal("4000.00"))  # Maximum


if __name__ == "__main__":
    unittest.main()
