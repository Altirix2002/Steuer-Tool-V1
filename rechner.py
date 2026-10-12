"""Berechnungen fuer das Steuer-Tool.

Wichtig: Das Programm rechnet nur mit Werten aus daten/tarife_2026.json.
Fehlt ein Wert (status 'fehlt'), wird dieser Teil NICHT berechnet.
Werte mit status 'zu_pruefen' werden verwendet, aber im Resultat als Warnung angezeigt.
Das Resultat ist eine Schaetzung. Verbindlich ist nur die Veranlagung des Steueramts.
"""

import json
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

DATEN_ORDNER = Path(__file__).parent / "daten"


class FehlendeDaten(Exception):
    """Ein noetiger Tarif ist noch nicht eingetragen."""


def lade_tarife(jahr=2026):
    pfad = DATEN_ORDNER / f"tarife_{jahr}.json"
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def chf(betrag):
    """Auf Rappen runden."""
    return Decimal(betrag).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- Bund

def bundessteuer(steuerbares_einkommen, tarife, verheiratet=False, kinder=0):
    """Direkte Bundessteuer nach Tarif (Art. 36 DBG).

    Annahme: Das Einkommen wird auf ganze 100 Franken abgerundet,
    weil der Tarif 'fuer je weitere 100 Franken' rechnet.
    """
    bund = tarife["bund"]
    tarif = bund["tarif_verheiratet" if verheiratet else "tarif_alleinstehend"]
    stufen = tarif["stufen"]

    einkommen = Decimal(steuerbares_einkommen).quantize(Decimal("1"), rounding=ROUND_DOWN)
    einkommen = (einkommen // 100) * 100

    steuer = Decimal("0")
    for stufe in stufen:
        ab = Decimal(stufe["ab"])
        if einkommen >= ab:
            schritte = (einkommen - ab) // 100
            steuer = Decimal(str(stufe["basis"])) + schritte * Decimal(str(stufe["satz_pro_100"]))
        else:
            break

    # Hoechste Stufe: Pauschalsatz auf das ganze Einkommen
    letzte = stufen[-1]
    if einkommen >= letzte["ab"]:
        steuer = einkommen * Decimal(str(letzte["satz_pro_100"])) / 100

    if kinder:
        steuer -= Decimal(bund["abzug_pro_kind_vom_steuerbetrag"]) * kinder
    if steuer < bund["mindeststeuer_wird_erhoben_ab"]:
        steuer = Decimal("0")
    return chf(steuer)


# ---------------------------------------------------------------- Kanton ZH

def _progressiv(betrag, stufen, satz_feld, teiler):
    """Rechnet einen Stufentarif 'x% fuer die ersten/weiteren y Franken'."""
    if not stufen:
        raise FehlendeDaten("Tarif ist noch nicht eingetragen")
    rest = Decimal(betrag)
    steuer = Decimal("0")
    for stufe in stufen:
        satz = Decimal(str(stufe[satz_feld])) / teiler
        if stufe["betrag"] is None:          # letzte Stufe: alles darueber
            steuer += rest * satz
            rest = Decimal("0")
            break
        teil = min(rest, Decimal(stufe["betrag"]))
        steuer += teil * satz
        rest -= teil
        if rest <= 0:
            break
    return chf(steuer)


def einfache_staatssteuer_einkommen(steuerbares_einkommen, tarife, verheiratet=False):
    zh = tarife["kanton_zh"]
    tarif = zh["einkommenssteuer_verheiratetentarif" if verheiratet else "einkommenssteuer_grundtarif"]
    if tarif["status"] == "fehlt":
        raise FehlendeDaten("Einkommenssteuertarif Kanton ZH fehlt. " + tarif.get("_wo_holen", "Siehe Steuergesetz ZH LS 631.1."))
    return _progressiv(steuerbares_einkommen, tarif["stufen"], "satz_prozent", 100)


def einfache_staatssteuer_vermoegen(steuerbares_vermoegen, tarife, verheiratet=False):
    zh = tarife["kanton_zh"]
    tarif = zh["vermoegenssteuer_verheiratetentarif" if verheiratet else "vermoegenssteuer_grundtarif"]
    if tarif["status"] == "fehlt":
        raise FehlendeDaten("Vermoegenssteuertarif Kanton ZH fehlt. " + tarif.get("_wo_holen", "Siehe Steuergesetz ZH LS 631.1."))
    return _progressiv(steuerbares_vermoegen, tarif["stufen"], "satz_promille", 1000)


# ---------------------------------------------------------------- Abzuege Bund (Hilfe)

def _uebrige_berufskosten(nettolohn, prozent, minimum, maximum):
    netto = Decimal(str(nettolohn))
    if netto <= 0:
        return Decimal(0)
    wert = netto * Decimal(str(prozent)) / 100
    wert = max(Decimal(str(minimum)), min(wert, Decimal(str(maximum))))
    return min(wert, netto)


def berufskosten_pauschale_bund(nettolohn, tarife):
    """Uebrige Berufskosten: Prozent vom Nettolohn, mindestens/hoechstens gemaess ESTV."""
    a = tarife["bund"]["abzuege"]
    return chf(_uebrige_berufskosten(nettolohn, a.get("uebrige_berufskosten_prozent", 3),
                                     a["uebrige_berufskosten_min"], a["uebrige_berufskosten_max"]))


def begrenze(betrag, maximum):
    return chf(min(Decimal(betrag), Decimal(maximum)))


def einkommen_aus_angaben(angaben, tarife, ebene="bund"):
    """Schaetzt das steuerbare Einkommen aus Lohn und Belegen.

    angaben: netto, neben, andere, fahr, verpf, pk (bool), s3a, kk (Versicherungspraemien),
             wb (Weiterbildung), zinsen (private Schuldzinsen), krankheit, spenden,
             kinder (int), ehepaar (bool)
    ebene: 'bund' oder 'kanton'
    Gibt (steuerbares_einkommen, zeilen) zurueck. zeilen = Liste (Text, Betrag), Abzuege negativ.
    Wirft FehlendeDaten, wenn ein noetiger Wert fuer diese Ebene fehlt.

    Schuldzinsen: abziehbar bis zum steuerbaren Vermoegensertrag plus 50'000 Franken
    (Art. 33 Abs. 1 lit. a DBG, Paragraph 31 Abs. 1 lit. a StG ZH). Vermoegensertraege werden
    hier nicht erfasst, darum gilt als Obergrenze nur der Sockel von 50'000 (vorsichtig).
    """
    def zahl(k):
        return Decimal(str(angaben.get(k) or 0))

    ehepaar = bool(angaben.get("ehepaar"))
    kinder = int(angaben.get("kinder") or 0)
    pk = angaben.get("pk", True)

    if ebene == "bund":
        a = tarife["bund"]["abzuege"]
        if a.get("status") == "fehlt":
            raise FehlendeDaten("Abzuege Bund fehlen fuer dieses Jahr.")
        verpf_max = a["verpflegung_voll_pro_jahr"]
        prozent, minimum, maximum = a.get("uebrige_berufskosten_prozent", 3), a["uebrige_berufskosten_min"], a["uebrige_berufskosten_max"]
    else:
        a = tarife["kanton_zh"].get("abzuege", {"status": "fehlt"})
        if a.get("status") == "fehlt":
            raise FehlendeDaten("Abzuege Kanton fehlen fuer dieses Jahr.")
        p = a["berufskosten_pauschalen"]
        if p.get("status") == "fehlt":
            raise FehlendeDaten("Pauschalen fuer Berufsauslagen Kanton fehlen. " + p.get("_wo_holen", ""))
        verpf_max = p["verpflegung_voll_pro_jahr"]
        prozent, minimum, maximum = p["uebrige_berufskosten_prozent"], p["uebrige_berufskosten_min"], p["uebrige_berufskosten_max"]

    zeilen = []
    netto = zahl("netto")
    einkuenfte = netto + zahl("neben") + zahl("andere")
    zeilen.append(("Einkuenfte (Lohn, Nebenerwerb, andere)", einkuenfte))

    fahr = min(zahl("fahr"), Decimal(a["fahrkosten_max"]))
    verpf = min(zahl("verpf"), Decimal(verpf_max))
    uebrige = _uebrige_berufskosten(netto, prozent, minimum, maximum)
    zeilen += [(f"Fahrkosten (max. {a['fahrkosten_max']})", -fahr),
               (f"Verpflegung (max. {verpf_max})", -verpf),
               (f"Uebrige Berufskosten ({prozent} %, {minimum} bis {maximum})", -uebrige)]

    max3a = tarife["saeule_3a"]["max_mit_pensionskasse" if pk else "max_ohne_pensionskasse"]
    s3a = min(zahl("s3a"), Decimal(max3a))
    zeilen.append((f"Saeule 3a (max. {max3a})", -s3a))

    mit_vorsorge = pk or s3a > 0
    vkey = ("versicherungspraemien_" + ("verheiratet" if ehepaar else "alleinstehend")
            + ("_mit_2_3a" if mit_vorsorge else "_ohne_2_3a"))
    vmax = Decimal(a[vkey]) + kinder * Decimal(a["versicherungspraemien_pro_kind"])
    vers = min(zahl("kk"), vmax)
    zeilen.append((f"Versicherungen (max. {vmax})", -vers))

    wb = min(zahl("wb"), Decimal(a["weiterbildung_max"]))
    if wb:
        zeilen.append((f"Weiterbildung (max. {a['weiterbildung_max']})", -wb))

    zinsen = zahl("zinsen")
    if zinsen:
        if "schuldzinsen_max_ohne_vermoegensertrag" not in a:
            raise FehlendeDaten("Grenze fuer Schuldzinsen fehlt fuer dieses Jahr.")
        zinsen = min(zinsen, Decimal(a["schuldzinsen_max_ohne_vermoegensertrag"]))
        zeilen.append(("Private Schuldzinsen", -zinsen))

    nettoeinkommen = einkuenfte - fahr - verpf - uebrige - s3a - vers - wb - zinsen
    basis = max(nettoeinkommen, Decimal(0))

    krank = max(Decimal(0), zahl("krankheit") - basis * Decimal(a["krankheitskosten_selbstbehalt_prozent"]) / 100)
    if krank:
        zeilen.append((f"Krankheitskosten (ueber {a['krankheitskosten_selbstbehalt_prozent']} % Selbstbehalt)", -krank))
    spenden = zahl("spenden")
    spenden = Decimal(0) if spenden < a["spenden_minimum"] else min(spenden, basis * Decimal(a["spenden_max_prozent"]) / 100)
    if spenden:
        zeilen.append((f"Spenden (max. {a['spenden_max_prozent']} %)", -spenden))

    sozial = kinder * Decimal(a["kinderabzug"])
    if kinder:
        zeilen.append((f"Kinderabzug ({kinder} x {a['kinderabzug']})", -sozial))
    if ebene == "bund" and ehepaar:
        sozial += Decimal(a["verheiratetenabzug"])
        zeilen.append(("Verheiratetenabzug", -Decimal(a["verheiratetenabzug"])))

    total = max(Decimal(0), nettoeinkommen - krank - spenden - sozial)
    return chf(total), zeilen


def ersparnis_3a(eingaben, tarife, betrag):
    """Wie viel Steuern spart eine (zusaetzliche) Einzahlung in die Saeule 3a?
    Vereinfachung: Der Betrag wird vom steuerbaren Einkommen bei Bund und Kanton abgezogen."""
    vorher = berechne(eingaben, tarife)
    betrag = Decimal(str(betrag))
    nachher_eingaben = dict(eingaben)
    nachher_eingaben["einkommen_bund"] = max(Decimal(str(eingaben["einkommen_bund"])) - betrag, Decimal(0))
    nachher_eingaben["einkommen_kanton"] = max(Decimal(str(eingaben["einkommen_kanton"])) - betrag, Decimal(0))
    nachher = berechne(nachher_eingaben, tarife)
    return vorher["total"] - nachher["total"]


# ---------------------------------------------------------------- Gesamt

def berechne(eingaben, tarife):
    """eingaben: dict mit
        einkommen_bund, einkommen_kanton, vermoegen_kanton,
        verheiratet (bool), kinder (int), kirche ('keine'|'reformiert'|...)
    Gibt ein dict mit Teilresultaten, Warnungen und fehlenden Teilen zurueck.
    """
    resultat = {"teile": {}, "warnungen": [], "fehlt": []}
    verh = eingaben.get("verheiratet", False)

    # Bund
    resultat["teile"]["Direkte Bundessteuer"] = bundessteuer(
        eingaben["einkommen_bund"], tarife, verh, eingaben.get("kinder", 0))

    # Kanton und Gemeinde
    zh = tarife["kanton_zh"]
    try:
        einfach = einfache_staatssteuer_einkommen(eingaben["einkommen_kanton"], tarife, verh)
        tarif_name = "einkommenssteuer_verheiratetentarif" if verh else "einkommenssteuer_grundtarif"
        if zh[tarif_name]["status"] != "verifiziert":
            resultat["warnungen"].append("Einkommenstarif Kanton noch pruefen (" + zh[tarif_name].get("_quelle", "") + ")")
        if eingaben.get("vermoegen_kanton"):
            try:
                einfach += einfache_staatssteuer_vermoegen(eingaben["vermoegen_kanton"], tarife, verh)
            except FehlendeDaten as fehler:
                resultat["fehlt"].append(str(fehler) + " Vermoegenssteuer ist NICHT enthalten.")
        resultat["teile"]["Einfache Staatssteuer (Basis)"] = einfach

        for name, eintrag in [("Staatssteuer", zh["steuerfuss_staat"]),
                              ("Gemeindesteuer", zh["steuerfuss_gemeinde"])]:
            resultat["teile"][f"{name} ({eintrag['wert_prozent']}%)"] = chf(einfach * eintrag["wert_prozent"] / 100)
            if eintrag["status"] != "verifiziert":
                resultat["warnungen"].append(f"Steuerfuss {name} noch pruefen ({eintrag['_quelle']})")

        kirche = eingaben.get("kirche", "keine")
        if kirche != "keine":
            satz = zh["steuerfuss_kirche"][kirche]
            resultat["teile"][f"Kirchensteuer ({satz}%)"] = chf(einfach * satz / 100)
            if zh["steuerfuss_kirche"]["status"] != "verifiziert":
                resultat["warnungen"].append("Kirchensteuerfuss noch pruefen")
    except FehlendeDaten as fehler:
        resultat["fehlt"].append(str(fehler))

    ps = zh["personalsteuer"]
    # Ehegatten schulden je die volle Personalsteuer (Paragraph 199 Abs. 2 StG ZH)
    ehepaar = eingaben.get("ehepaar", verh)
    resultat["teile"]["Personalsteuer"] = chf(ps["wert"] * (2 if ehepaar else 1))
    if ps["status"] != "verifiziert":
        resultat["warnungen"].append("Personalsteuer noch pruefen (" + ps["_quelle"] + ")")

    resultat["warnungen"].append(
        "Annahme: Einkommen fuer die Bundessteuer auf 100 Franken abgerundet (Tarifaufbau). "
        "Kanton: keine Rundung angenommen.")
    resultat["total"] = chf(sum(v for k, v in resultat["teile"].items()
                                if not k.startswith("Einfache")))
    return resultat


def frist_info(tarife, heute, eigene=None):
    """Einreichefrist fuer die Steuererklaerung, verbleibende Tage und Dringlichkeit.

    eigene: ISO-Datum der eigenen Frist (z.B. nach Fristerstreckung), gilt statt der Standardfrist.
    stufe: 'normal', 'bald' (hoechstens 30 Tage), 'dringend' (hoechstens 7 Tage oder ueberschritten).
    Gibt None zurueck, wenn weder eine eigene noch eine Standardfrist vorhanden ist.
    """
    standard = (tarife.get("fristen") or {}).get("einreichefrist", {}).get("datum")
    iso = eigene or standard
    if not iso:
        return None
    frist = date.fromisoformat(iso)
    tage = (frist - heute).days
    stufe = "dringend" if tage <= 7 else "bald" if tage <= 30 else "normal"
    return {"frist": frist, "tage": tage, "stufe": stufe, "eigene": bool(eigene)}


def monate_bis_jahresende(jahr, heute):
    """Anzahl Monate (inklusive laufender Monat) bis Ende des Steuerjahres."""
    if jahr > heute.year:
        return 12
    if jahr < heute.year:
        return 0
    return 12 - (heute.month - 1)


def zuruecklegen(steuer, schon, jahr, heute):
    """Wie viel pro Monat zuruecklegen? steuer und schon in Franken.

    pro_monat: Steuer geteilt durch 12. fehlt: was noch nicht zurueckgelegt ist.
    pro_monat_bis_ende: fehlt geteilt durch die Monate bis Ende Steuerjahr (None, wenn keine mehr uebrig).
    """
    steuer, schon = Decimal(str(steuer)), Decimal(str(schon))
    monate = monate_bis_jahresende(jahr, heute)
    fehlt = max(Decimal(0), steuer - schon)
    return {
        "pro_monat": chf(steuer / 12),
        "fehlt": chf(fehlt),
        "ueberschuss": chf(max(Decimal(0), schon - steuer)),
        "monate": monate,
        "pro_monat_bis_ende": chf(fehlt / monate) if monate else None,
    }


def sicherung_faellig(letzte, jetzt, hat_daten, tage=30):
    """Soll die App an eine Sicherung erinnern?

    letzte: Zeitpunkt der letzten Sicherung (datetime) oder None, wenn noch nie gesichert wurde.
    Ohne bisherige Sicherung wird nur erinnert, wenn schon Daten eingegeben sind.
    """
    if letzte is None:
        return bool(hat_daten)
    return (jetzt - letzte).days > tage
