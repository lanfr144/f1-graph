"""Transforme le cache brut de l'API en lignes prêtes à charger dans Neo4j.

Aucun accès réseau, aucun accès à Neo4j : ce module se teste seul
(`python transformer.py` affiche un bilan et vérifie l'unicité des clés).

Règles :
  * une valeur absente de la source reste absente (None) — jamais de valeur par défaut ;
  * une valeur présente mais illisible lève une erreur qui nomme l'enregistrement ;
  * une clé en double lève une erreur avant tout chargement.
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
from collections import Counter

from commun import CACHE, lire_pages

log = logging.getLogger("f1.transformation")

# Représentations d'une absence de valeur rencontrées dans la source. L'API publie
# parfois le texte "None" (un None Python sérialisé tel quel) au lieu de null : par
# exemple le numéro de voiture de six engagés forfaits en 1961-1963.
NULS_SOURCE = ("", "None", "null")


class DonneeInvalide(ValueError):
    pass


# --- Conversions ------------------------------------------------------------

def _vide(v) -> bool:
    return v is None or v in NULS_SOURCE


def entier(v, ctx: str) -> int | None:
    if _vide(v):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise DonneeInvalide(f"{ctx} : entier attendu, reçu {v!r}") from None


def reel(v, ctx: str) -> float | None:
    if _vide(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise DonneeInvalide(f"{ctx} : nombre attendu, reçu {v!r}") from None


def date_iso(v, ctx: str) -> dt.date | None:
    if _vide(v):
        return None
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        raise DonneeInvalide(f"{ctx} : date AAAA-MM-JJ attendue, reçu {v!r}") from None


def instant(date: str | None, heure: str | None, ctx: str) -> dt.datetime | None:
    """date + heure UTC ('15:00:00Z') -> datetime avec fuseau ; None si l'heure manque."""
    if _vide(date) or _vide(heure):
        return None
    try:
        valeur = dt.datetime.fromisoformat(f"{date}T{heure}")
    except ValueError:
        raise DonneeInvalide(f"{ctx} : horodatage illisible {date!r} {heure!r}") from None
    if valeur.tzinfo is None:
        # Sans fuseau, l'instant serait ambigu : on refuse plutôt que de supposer UTC.
        raise DonneeInvalide(f"{ctx} : heure sans fuseau {heure!r}")
    return valeur


def chrono_ms(v, ctx: str) -> int | None:
    """'1:31:44.742', '1:32.608', '25.208' -> millisecondes."""
    if _vide(v):
        return None
    try:
        parties = v.split(":")
        if len(parties) > 3:
            raise ValueError
        secondes = 0.0
        for p in parties[:-1]:
            secondes = secondes * 60 + int(p)
        return round((secondes * 60 + float(parties[-1])) * 1000)
    except ValueError:
        raise DonneeInvalide(f"{ctx} : chrono illisible {v!r}") from None


def heure_locale(v, ctx: str) -> dt.time | None:
    if _vide(v):
        return None
    try:
        return dt.time.fromisoformat(v)
    except ValueError:
        raise DonneeInvalide(f"{ctx} : heure illisible {v!r}") from None


def race_id(saison, manche) -> str:
    return f"{int(saison)}-{int(manche):02d}"


# --- Lecture du cache ---------------------------------------------------------

def saisons_en_cache() -> list[int]:
    if not CACHE.is_dir():
        return []
    return sorted(int(d.name) for d in CACHE.iterdir() if d.is_dir() and d.name.isdigit())


def _courses(chemin: str) -> list[dict]:
    return [r for p in lire_pages(chemin) for r in p["RaceTable"]["Races"]]


def _pilote(d: dict) -> dict:
    ctx = f"pilote {d['driverId']}"
    prenom, nom = d.get("givenName"), d.get("familyName")
    return {
        "k": d["driverId"],
        "nationality": d.get("nationality") or None,
        "p": {
            "givenName": prenom or None,
            "familyName": nom or None,
            "fullName": " ".join(x for x in (prenom, nom) if x) or None,
            "code": d.get("code") or None,
            # Numéro permanent ACTUEL du pilote : l'API ne donne pas son historique.
            "permanentNumber": entier(d.get("permanentNumber"), ctx),
            "dateOfBirth": date_iso(d.get("dateOfBirth"), ctx),
            "url": d.get("url") or None,
        },
    }


def _constructeur(c: dict) -> dict:
    return {
        "k": c["constructorId"],
        "nationality": c.get("nationality") or None,
        "p": {"name": c.get("name") or None, "url": c.get("url") or None},
    }


def _circuit(c: dict) -> dict:
    ctx = f"circuit {c['circuitId']}"
    loc = c.get("Location") or {}
    return {
        "k": c["circuitId"],
        "country": loc.get("country") or None,
        "lat": reel(loc.get("lat"), ctx),
        "lng": reel(loc.get("long"), ctx),
        "p": {
            "name": c.get("circuitName") or None,
            "url": c.get("url") or None,
            "locality": loc.get("locality") or None,
            "latitude": reel(loc.get("lat"), ctx),
            "longitude": reel(loc.get("long"), ctx),
        },
    }


# Sessions annexes publiées dans le calendrier (selon les saisons).
SESSIONS = {
    "FirstPractice": "firstPractice",
    "SecondPractice": "secondPractice",
    "ThirdPractice": "thirdPractice",
    "Qualifying": "qualifying",
    "Sprint": "sprint",
    "SprintShootout": "sprintShootout",
    "SprintQualifying": "sprintQualifying",
}


def _course(r: dict) -> dict:
    rid = race_id(r["season"], r["round"])
    ctx = f"course {rid}"
    p = {
        "season": int(r["season"]),
        "round": int(r["round"]),
        "name": r.get("raceName") or None,
        "url": r.get("url") or None,
        "date": date_iso(r.get("date"), ctx),
        "startsAt": instant(r.get("date"), r.get("time"), ctx),
    }
    for cle, prefixe in SESSIONS.items():
        s = r.get(cle) or {}
        p[f"{prefixe}Date"] = date_iso(s.get("date"), f"{ctx} {cle}")
        p[f"{prefixe}StartsAt"] = instant(s.get("date"), s.get("time"), f"{ctx} {cle}")
    return {"k": rid, "season": int(r["season"]), "circuitId": r["Circuit"]["circuitId"], "p": p}


def cle_resultat(rid: str, numero, pilote: str, quoi: str) -> str:
    """'AAAA-RR-<numéro>-<pilote>' ; sans numéro, 'AAAA-RR-sans-numero-<pilote>'.

    Le numéro distingue deux voitures d'un même pilote dans une course (années 1950).
    Quand la source n'en donne pas, la clé s'en passe ; si elle n'est alors plus
    unique, verifier_unicite() arrêtera tout avant chargement.
    """
    if _vide(numero):
        log.warning("%s %s %s : numéro de voiture absent dans la source (%r), clé sans numéro",
                    quoi, rid, pilote, numero)
        return f"{rid}-sans-numero-{pilote}"
    return f"{rid}-{numero}-{pilote}"


def _resultat(rid: str, x: dict, avec_vitesse: bool) -> dict:
    pilote = x["Driver"]["driverId"]
    numero = x.get("number")
    ctx = f"résultat {rid} {pilote}"
    temps = x.get("Time") or {}
    mt = x.get("FastestLap") or {}
    p = {
        "number": entier(numero, ctx),
        "grid": entier(x.get("grid"), ctx),
        "position": entier(x.get("position"), ctx),
        "positionText": x.get("positionText") or None,
        "points": reel(x.get("points"), ctx),
        "laps": entier(x.get("laps"), ctx),
        "time": temps.get("time") or None,
        "timeMillis": entier(temps.get("millis"), ctx),
        "fastestLapRank": entier(mt.get("rank"), ctx),
        "fastestLapNumber": entier(mt.get("lap"), ctx),
        "fastestLapTime": (mt.get("Time") or {}).get("time") or None,
        "fastestLapMillis": chrono_ms((mt.get("Time") or {}).get("time"), ctx),
    }
    if avec_vitesse:
        vitesse = mt.get("AverageSpeed") or {}
        if vitesse and vitesse.get("units") != "kph":
            raise DonneeInvalide(f"{ctx} : unité de vitesse inattendue {vitesse.get('units')!r}")
        p["fastestLapAvgSpeedKph"] = reel(vitesse.get("speed"), ctx)
    if p["positionText"] is None or p["points"] is None:
        raise DonneeInvalide(f"{ctx} : positionText ou points absent")
    return {
        "k": cle_resultat(rid, numero, pilote, "résultat"),
        "raceId": rid,
        "driverId": pilote,
        "constructorId": x["Constructor"]["constructorId"],
        "status": x.get("status") or None,
        "p": p,
    }


def _qualif(rid: str, x: dict) -> dict:
    pilote = x["Driver"]["driverId"]
    numero = x.get("number")
    ctx = f"qualification {rid} {pilote}"
    p = {"number": entier(numero, ctx), "position": entier(x.get("position"), ctx)}
    for q in ("Q1", "Q2", "Q3"):
        p[q.lower()] = x.get(q) or None
        p[f"{q.lower()}Millis"] = chrono_ms(x.get(q), f"{ctx} {q}")
    return {"k": cle_resultat(rid, numero, pilote, "qualification"), "raceId": rid, "driverId": pilote,
            "constructorId": x["Constructor"]["constructorId"], "p": p}


def _classement(saison: int, chemin: str, liste: str, nature: str, objet: str, cle_id: str):
    lignes = []
    for page in lire_pages(f"{saison}/{chemin}"):
        for sl in page["StandingsTable"]["StandingsLists"]:
            apres = entier(sl.get("round"), f"classement {saison}")
            for x in sl[liste]:
                ident = x[objet][cle_id]
                ctx = f"classement {nature} {saison} {ident}"
                p = {
                    "season": saison,
                    "afterRound": apres,
                    "position": entier(x.get("position"), ctx),
                    "positionText": x.get("positionText") or None,
                    "points": reel(x.get("points"), ctx),
                    "wins": entier(x.get("wins"), ctx),
                }
                if p["points"] is None:
                    raise DonneeInvalide(f"{ctx} : points absents")
                lignes.append({"key": f"{nature}:{saison}:{ident}", "a": ident, "b": saison,
                               "p": p, "_brut": x})
    return lignes


def verifier_unicite(lignes: list[dict], cle: str, nom: str) -> None:
    doublons = [k for k, n in Counter(l[cle] for l in lignes).items() if n > 1]
    if doublons:
        raise DonneeInvalide(f"{nom} : {len(doublons)} clé(s) en double, ex. {doublons[:5]}")


# --- Transformation complète -------------------------------------------------

def transformer(saisons: list[int] | None = None) -> dict[str, list[dict]]:
    # None : toutes les saisons en cache ; [] : référentiels seuls, aucune saison.
    saisons = saisons_en_cache() if saisons is None else saisons

    pilotes: dict[str, dict] = {}
    constructeurs: dict[str, dict] = {}
    circuits: dict[str, dict] = {}

    # Les listes de référence font foi ; les objets imbriqués comblent les absents.
    for page in lire_pages("drivers"):
        for d in page["DriverTable"]["Drivers"]:
            pilotes[d["driverId"]] = _pilote(d)
    for page in lire_pages("constructors"):
        for c in page["ConstructorTable"]["Constructors"]:
            constructeurs[c["constructorId"]] = _constructeur(c)
    for page in lire_pages("circuits"):
        for c in page["CircuitTable"]["Circuits"]:
            circuits[c["circuitId"]] = _circuit(c)

    toutes_saisons = {int(s["season"]): s.get("url") or None
                      for page in lire_pages("seasons") for s in page["SeasonTable"]["Seasons"]}
    statuts = {s["status"] for page in lire_pages("status") for s in page["StatusTable"]["Status"]}

    courses, resultats, sprints, qualifs, arrets, tours = [], [], [], [], [], []
    classement_pilotes, classement_constructeurs = [], []
    ecuries: dict[str, dict] = {}

    def noter_ecurie(saison: int, pilote: str, constructeur: str) -> None:
        cle = f"{saison}:{pilote}:{constructeur}"
        ecuries[cle] = {"key": cle, "a": pilote, "b": constructeur, "p": {"season": saison}}

    def noter_imbriques(x: dict) -> None:
        if "Driver" in x:
            pilotes.setdefault(x["Driver"]["driverId"], _pilote(x["Driver"]))
        if "Constructor" in x:
            constructeurs.setdefault(x["Constructor"]["constructorId"], _constructeur(x["Constructor"]))
        for c in x.get("Constructors", []):
            constructeurs.setdefault(c["constructorId"], _constructeur(c))

    for saison in saisons:
        if saison not in toutes_saisons:
            raise DonneeInvalide(f"saison {saison} en cache mais absente de la liste des saisons")
        calendrier = _courses(f"{saison}/races")
        connues = set()
        for r in calendrier:
            circuits.setdefault(r["Circuit"]["circuitId"], _circuit(r["Circuit"]))
            c = _course(r)
            courses.append(c)
            connues.add(c["k"])

        def course_connue(r: dict, quoi: str) -> str:
            rid = race_id(r["season"], r["round"])
            if rid not in connues:
                raise DonneeInvalide(f"{quoi} pour la course {rid}, absente du calendrier {saison}")
            return rid

        for r in _courses(f"{saison}/results"):
            rid = course_connue(r, "résultats")
            for x in r["Results"]:
                noter_imbriques(x)
                resultats.append(_resultat(rid, x, avec_vitesse=True))
                noter_ecurie(saison, x["Driver"]["driverId"], x["Constructor"]["constructorId"])
        for r in _courses(f"{saison}/sprint"):
            rid = course_connue(r, "sprint")
            for x in r["SprintResults"]:
                noter_imbriques(x)
                sprints.append(_resultat(rid, x, avec_vitesse=False))
                noter_ecurie(saison, x["Driver"]["driverId"], x["Constructor"]["constructorId"])
        for r in _courses(f"{saison}/qualifying"):
            rid = course_connue(r, "qualifications")
            for x in r["QualifyingResults"]:
                noter_imbriques(x)
                qualifs.append(_qualif(rid, x))
                noter_ecurie(saison, x["Driver"]["driverId"], x["Constructor"]["constructorId"])

        for ligne in _classement(saison, "driverstandings", "DriverStandings", "driver", "Driver", "driverId"):
            noter_imbriques(ligne["_brut"])
            for c in ligne.pop("_brut")["Constructors"]:
                noter_ecurie(saison, ligne["a"], c["constructorId"])
            classement_pilotes.append(ligne)
        for ligne in _classement(saison, "constructorstandings", "ConstructorStandings",
                                 "constructor", "Constructor", "constructorId"):
            noter_imbriques(ligne.pop("_brut"))
            classement_constructeurs.append(ligne)

        for c in [c for c in courses if c["season"] == saison]:
            manche = c["p"]["round"]
            for r in _courses(f"{saison}/{manche}/pitstops"):
                rid = course_connue(r, "arrêts")
                for x in r.get("PitStops", []):
                    ctx = f"arrêt {rid} {x['driverId']} {x.get('stop')}"
                    arrets.append({
                        "k": f"{rid}-{x['driverId']}-{x['stop']}", "raceId": rid, "driverId": x["driverId"],
                        "p": {"stop": entier(x.get("stop"), ctx), "lap": entier(x.get("lap"), ctx),
                              "timeOfDay": heure_locale(x.get("time"), ctx),
                              "duration": x.get("duration") or None,
                              "durationMillis": chrono_ms(x.get("duration"), ctx)},
                    })
            for r in _courses(f"{saison}/{manche}/laps"):
                rid = course_connue(r, "tours")
                for tour in r.get("Laps", []):
                    for t in tour["Timings"]:
                        ctx = f"tour {rid} {t['driverId']} {tour['number']}"
                        tours.append({
                            "k": f"{rid}-{t['driverId']}-{tour['number']}", "raceId": rid,
                            "driverId": t["driverId"],
                            "p": {"lap": entier(tour["number"], ctx), "position": entier(t.get("position"), ctx),
                                  "time": t.get("time") or None, "millis": chrono_ms(t.get("time"), ctx)},
                        })

    for r in resultats + sprints:
        if r["status"] is None:
            raise DonneeInvalide(f"résultat {r['k']} : statut absent")
        statuts.add(r["status"])

    sortie = {
        "saisons": [{"k": a, "p": {"url": u}} for a, u in sorted(toutes_saisons.items())],
        "circuits": list(circuits.values()),
        "pilotes": list(pilotes.values()),
        "constructeurs": list(constructeurs.values()),
        "statuts": [{"k": s, "p": {}} for s in sorted(statuts)],
        "courses": courses,
        "resultats": resultats,
        "sprints": sprints,
        "qualifications": qualifs,
        "arrets": arrets,
        "tours": tours,
        "pilote_ecurie": list(ecuries.values()),
        "classement_pilotes": classement_pilotes,
        "classement_constructeurs": classement_constructeurs,
    }
    for nom in ("saisons", "circuits", "pilotes", "constructeurs", "statuts", "courses",
                "resultats", "sprints", "qualifications", "arrets", "tours"):
        verifier_unicite(sortie[nom], "k", nom)
    for nom in ("pilote_ecurie", "classement_pilotes", "classement_constructeurs"):
        verifier_unicite(sortie[nom], "key", nom)
    return sortie


if __name__ == "__main__":
    try:
        donnees = transformer()
    except DonneeInvalide as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Saisons en cache : {saisons_en_cache() or 'aucune'}")
    for nom, lignes in donnees.items():
        print(f"  {nom:26} {len(lignes):>8}")
