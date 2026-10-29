"""Données complémentaires, hors de l'API Jolpica-F1.

1. Académies de pilotes (programmes de jeunes pilotes des écuries), lues dans les
   articles Wikipédia en anglais listés par referentiel/academies.csv. Chaque ligne de
   tableau donne un pilote (lien vers son article) et ses années dans le programme.
   Le pilote est rattaché au nœud Driver du graphe par le TITRE CANONIQUE de son
   article (redirections résolues par l'API de Wikipédia), comparé à celui de l'URL
   Wikipédia que l'API F1 donne pour chaque pilote : aucun rapprochement par nom.
   Les juniors qui n'ont jamais couru en F1 ne correspondent à aucun Driver : ils sont
   comptés dans le journal et ignorés, pas inventés.

2. Pilotes et écuries suivis par la rédaction : referentiel/suivis.csv, tenu par la
   rédaction elle-même ; aucun suivi n'est deviné.

Sources mises en cache dans donnees/referentiels/wikipedia/ (non versionné, licence
CC BY-SA 4.0), avec révision, URL de la révision et empreinte, reprises par SOURCES.md.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from commun import DONNEES, RACINE, USER_AGENT

log = logging.getLogger("f1.complements")

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI = "https://en.wikipedia.org/wiki/"
DOSSIER = DONNEES / "referentiels" / "wikipedia"
FRAICHEUR_JOURS = 7          # une page en cache depuis plus longtemps est relue
TABLE_ACADEMIES = RACINE / "referentiel" / "academies.csv"
TABLE_SUIVIS = RACINE / "referentiel" / "suivis.csv"


class ComplementInvalide(ValueError):
    pass


# --- Accès à Wikipédia ---------------------------------------------------------

def _api(params: dict) -> dict:
    url = WIKI_API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2, "maxlag": 5})
    for tentative in range(1, 6):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                donnees = json.loads(r.read())
            if "error" in donnees and donnees["error"].get("code") == "maxlag":
                raise urllib.error.URLError("maxlag")
            if "error" in donnees:
                raise ComplementInvalide(f"Wikipédia : {donnees['error'].get('info')}")
            return donnees
        except (urllib.error.URLError, TimeoutError) as e:
            attente = 10 * tentative
            if isinstance(e, urllib.error.HTTPError) and e.headers.get("Retry-After", "").isdigit():
                attente = max(attente, int(e.headers["Retry-After"]))
            log.warning("  Wikipédia indisponible (%s) : nouvel essai %d/5 dans %d s", e, tentative, attente)
            time.sleep(attente)
    raise ComplementInvalide(f"Wikipédia injoignable : {url}")


def _cle(titre: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", titre).strip("_")


def page(titre: str, forcer: bool = False) -> dict:
    """Wikitexte d'une page, depuis le cache s'il a moins de FRAICHEUR_JOURS jours."""
    DOSSIER.mkdir(parents=True, exist_ok=True)
    fichier, meta = DOSSIER / f"{_cle(titre)}.json", DOSSIER / f"{_cle(titre)}.json.meta.json"
    if fichier.exists() and not forcer:
        age = time.time() - fichier.stat().st_mtime
        if age < FRAICHEUR_JOURS * 86400:
            return json.loads(fichier.read_text(encoding="utf-8"))
    donnees = _api({"action": "parse", "page": titre, "prop": "wikitext|revid", "redirects": 1})["parse"]
    contenu = {"titre": donnees["title"], "revid": donnees["revid"], "wikitext": donnees["wikitext"],
               "url": f"{WIKI_API.replace('/w/api.php', '/w/index.php')}?oldid={donnees['revid']}"}
    corps = json.dumps(contenu, ensure_ascii=False).encode("utf-8")
    provisoire = fichier.with_name(fichier.name + ".tmp")
    provisoire.write_bytes(corps)
    provisoire.replace(fichier)
    meta.write_text(json.dumps({
        "url": contenu["url"], "titre": contenu["titre"], "revid": contenu["revid"],
        "recupere_le": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(corps).hexdigest(), "octets": len(corps),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("  Wikipédia « %s » : révision %s téléchargée", contenu["titre"], contenu["revid"])
    return contenu


def canoniques(titres: set[str], forcer: bool = False) -> dict[str, str | None]:
    """Titre -> titre canonique (normalisé, redirections suivies) ; None si la page n'existe pas."""
    cache_f = DOSSIER / "titres-canoniques.json"
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() and not forcer else {}
    manquants = sorted(t for t in titres if t not in cache)
    for i in range(0, len(manquants), 50):
        lot = manquants[i:i + 50]
        time.sleep(1)  # politesse envers l'API de Wikipédia (limite de débit constatée)
        r = _api({"action": "query", "titles": "|".join(lot), "redirects": 1})["query"]
        vers = {t: t for t in lot}
        for etape in ("normalized", "redirects"):
            for x in r.get(etape, []):
                for source, cible in list(vers.items()):
                    if cible == x["from"]:
                        vers[source] = x["to"]
        absents = {p["title"] for p in r.get("pages", []) if p.get("missing") or p.get("invalid")}
        for t in lot:
            cache[t] = None if vers[t] in absents else vers[t]
    if manquants:
        DOSSIER.mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("  Wikipédia : %d titre(s) résolu(s) en titres canoniques", len(manquants))
    return {t: cache.get(t) for t in titres}


def titre_de_url(url: str | None) -> str | None:
    """'http://en.wikipedia.org/wiki/Nico_H%C3%BClkenberg' -> 'Nico Hülkenberg'."""
    if not url or "/wiki/" not in url:
        return None
    return urllib.parse.unquote(url.split("/wiki/", 1)[1]).replace("_", " ").split("#")[0]


# --- Lecture des tableaux wiki ---------------------------------------------------

def _nettoyer(texte: str) -> str:
    texte = re.sub(r"<!--.*?-->", "", texte, flags=re.S)
    texte = re.sub(r"<ref[^>/]*/>", "", texte)
    texte = re.sub(r"<ref[^>]*>.*?</ref>", "", texte, flags=re.S)
    # {{sortname|Prénom|Nom}} ou {{sortname|Prénom|Nom|Cible}} : un lien vers le pilote.
    def sortname(m):
        args = [a.strip() for a in m[1].split("|") if "=" not in a]
        cible = args[2] if len(args) > 2 and args[2] else f"{args[0]} {args[1]}" if len(args) > 1 else args[0]
        return f"[[{cible}]]"
    texte = re.sub(r"\{\{\s*sortname\s*\|([^{}]*)\}\}", sortname, texte, flags=re.I)
    texte = re.sub(r"\{\{\s*(?:flagicon|flag|flagathlete|nowrap|small)[^{}]*\}\}", "", texte, flags=re.I)
    return texte


def _separer(ligne: str, sep: str) -> list[str]:
    """Découpe sur `sep` hors des [[…]] et {{…}}."""
    morceaux, profondeur, courant, i = [], 0, "", 0
    while i < len(ligne):
        if ligne.startswith(("[[", "{{"), i):
            profondeur += 1; courant += ligne[i:i + 2]; i += 2; continue
        if ligne.startswith(("]]", "}}"), i):
            profondeur = max(0, profondeur - 1); courant += ligne[i:i + 2]; i += 2; continue
        if profondeur == 0 and ligne.startswith(sep, i):
            morceaux.append(courant); courant = ""; i += len(sep); continue
        courant += ligne[i]; i += 1
    morceaux.append(courant)
    return morceaux


def _cellule(brut: str) -> tuple[str, int]:
    """Retire les attributs (« align=center| … ») ; renvoie (contenu, rowspan)."""
    parties = _separer(brut, "|")
    if len(parties) > 1 and "=" in parties[0] and "[[" not in parties[0] and "{{" not in parties[0]:
        attributs, contenu = parties[0], "|".join(parties[1:])
    else:
        attributs, contenu = "", brut
    m = re.search(r'rowspan\s*=\s*"?(\d+)', attributs)
    return contenu.strip(), int(m[1]) if m else 1


def tableaux(wikitext: str) -> list[dict]:
    """Tableaux wiki : section, en-têtes, lignes (rowspan reporté sur les lignes suivantes)."""
    resultat, section, courant, ligne_c, reports = [], "", None, None, {}
    for ligne in _nettoyer(wikitext).splitlines():
        s = ligne.strip()
        m = re.match(r"^(=+)\s*(.*?)\s*\1$", s)
        if m and courant is None:
            section = m[2]
            continue
        if s.startswith("{|"):
            courant, ligne_c, reports = {"section": section, "entetes": [], "lignes": []}, None, {}
            donnees_vues = False
        elif courant is None:
            continue
        elif s.startswith("|}"):
            if ligne_c:
                courant["lignes"].append(ligne_c)
            resultat.append(courant)
            courant = None
        elif s.startswith("|-"):
            if ligne_c:
                courant["lignes"].append(ligne_c)
            ligne_c = []
        elif s.startswith("|+"):
            continue
        elif s.startswith("!") and not donnees_vues:
            courant["entetes"] += [_cellule(c)[0] for c in _separer(s[1:], "!!")]
        elif s.startswith("|") or s.startswith("!"):
            donnees_vues = True
            if ligne_c is None:
                ligne_c = []
            for brut in _separer(s[1:], "||"):
                # Cellules reportées par un rowspan d'une ligne précédente.
                while len(ligne_c) in reports:
                    texte, reste = reports.pop(len(ligne_c))
                    ligne_c.append(texte)
                    if reste > 1:
                        reports[len(ligne_c) - 1] = (texte, reste - 1)
                texte, rowspan = _cellule(brut)
                if rowspan > 1:
                    reports[len(ligne_c)] = (texte, rowspan - 1)
                ligne_c.append(texte)
        elif ligne_c:
            ligne_c[-1] += "\n" + ligne  # suite d'une cellule sur plusieurs lignes
    return resultat


def periodes(texte: str) -> list[tuple[int, int | None]]:
    """'2010–2013, 2015' -> [(2010, 2013), (2015, 2015)] ; '2023–' -> [(2023, None)] (en cours)."""
    texte = re.sub(r"<[^>]+>", " ", texte).replace("&ndash;", "–").replace("&mdash;", "—")
    resultat = []
    for m in re.finditer(r"(?<!\d)((?:19|20)\d{2})(?!\d)\s*(?:(–|—|-|to)\s*((?:19|20)?\d{2}(?!\d)|present|current)?)?",
                         texte, flags=re.I):
        debut = int(m[1])
        if not m[2]:
            resultat.append((debut, debut))
        elif not m[3] or m[3].lower() in ("present", "current"):
            resultat.append((debut, None))
        else:
            fin = int(m[3]) if len(m[3]) == 4 else int(str(debut)[:2] + m[3])
            resultat.append((debut, fin))
    return resultat


def premier_lien(texte: str) -> str | None:
    m = re.search(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", texte)
    return m[1].strip() if m else None


# --- Transformation ---------------------------------------------------------------

def _lire_csv(chemin) -> list[dict]:
    with chemin.open(encoding="utf-8") as f:
        return [l for l in csv.DictReader(f, delimiter=";")]


def academies(pilotes: list[dict], constructeurs: list[dict], telecharger: bool) -> dict:
    """Nœuds Academy, liens FEEDS et MEMBER_OF, statistiques de rapprochement."""
    ids_ecuries = {c["k"] for c in constructeurs}
    titres_pilotes = {p["k"]: titre_de_url(p["p"].get("url")) for p in pilotes}
    lignes_csv = _lire_csv(TABLE_ACADEMIES)
    inconnues = [(l["academyId"], e) for l in lignes_csv for e in l["ecuries"].split("|") if e not in ids_ecuries]
    if inconnues:
        raise ComplementInvalide(f"{TABLE_ACADEMIES.name} : écurie(s) inconnue(s) du graphe : {inconnues}")

    pages, liens = {}, set()
    for l in lignes_csv:
        if telecharger:
            pages[l["academyId"]] = page(l["page_wikipedia"])
        else:
            fichier = DOSSIER / f"{_cle(l['page_wikipedia'])}.json"
            if not fichier.exists():
                raise ComplementInvalide(f"page Wikipédia « {l['page_wikipedia']} » absente du cache")
            pages[l["academyId"]] = json.loads(fichier.read_text(encoding="utf-8"))
    brutes = {}
    for aid, pg in pages.items():
        brutes[aid] = []
        for t in tableaux(pg["wikitext"]):
            # Sections hors sujet : pilotes e-sport (simulation) et tableaux de résultats.
            if re.search(r"esports?|sim racing|results", t["section"], re.I):
                continue
            entetes = [re.sub(r"\{\{[^|}]*\|([^|}]*).*?\}\}", r"\1", e).lower() for e in t["entetes"]]
            col_p = next((i for i, e in enumerate(entetes) if re.search(r"\b(driver|name)\b", e)), None)
            # Années DANS l'académie. Dans les tableaux des diplômés, c'est la colonne
            # « Junior Team / Academy experience » : la colonne « Years » y donne les
            # années en F1 (la prendre ferait d'Ocon un junior Mercedes jusqu'en 2026).
            col_a = next((i for i, e in enumerate(entetes)
                          if re.search(r"\b(junior|academy|programme|team)\b.*\bexperience\b", e)
                          and "f1" not in e), None)
            if col_a is None:
                col_a = next((i for i, e in enumerate(entetes) if re.search(r"\byears?\b", e)), None)
            if col_p is None or col_a is None:
                continue
            for ligne in t["lignes"]:
                if len(ligne) <= max(col_p, col_a):
                    continue
                cible = premier_lien(ligne[col_p])
                if cible:
                    liens.add(cible)
                brutes[aid].append({"section": t["section"], "cible": cible,
                                    "periodes": periodes(ligne[col_a]), "brut": ligne[col_p][:60]})

    if telecharger:
        canon = canoniques(liens | {t for t in titres_pilotes.values() if t})
    else:
        f = DOSSIER / "titres-canoniques.json"
        canon = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    par_titre = {}
    for driver_id, titre in titres_pilotes.items():
        c = canon.get(titre) if titre else None
        if c:
            par_titre[c] = driver_id

    noeuds, adhesions, stats = [], {}, {}
    for l in lignes_csv:
        aid, pg = l["academyId"], pages[l["academyId"]]
        noeuds.append({"k": aid, "constructeurs": l["ecuries"].split("|"),
                       "p": {"name": l["nom"], "wikipedia": WIKI + pg["titre"].replace(" ", "_"),
                             "revision": pg["revid"], "sourceUrl": pg["url"]}})
        st = {"lignes": len(brutes[aid]), "rattaches": 0, "sans_lien": 0, "hors_f1": 0, "sans_annees": 0}
        for b in brutes[aid]:
            if not b["cible"]:
                st["sans_lien"] += 1; continue
            driver_id = par_titre.get(canon.get(b["cible"]) or "")
            if not driver_id:
                st["hors_f1"] += 1; continue
            if not b["periodes"]:
                st["sans_annees"] += 1
                log.warning("  %s : %s sans années lisibles (%r), ignoré", aid, driver_id, b["brut"])
                continue
            st["rattaches"] += 1
            for debut, fin in b["periodes"]:
                cle = f"{aid}:{driver_id}:{debut}"
                adhesions[cle] = {"key": cle, "a": driver_id, "b": aid,
                                  "p": {"fromYear": debut, "toYear": fin, "ongoing": fin is None,
                                        "section": b["section"]}}
        stats[aid] = st
        log.info("  académie %-17s %3d ligne(s) : %3d pilote(s) de F1 rattaché(s), %3d junior(s) "
                 "sans carrière en F1, %d sans lien", aid, st["lignes"], st["rattaches"], st["hors_f1"],
                 st["sans_lien"])
    return {"academies": noeuds, "adhesions": list(adhesions.values()), "stats": stats}


def suivis(pilotes: list[dict], constructeurs: list[dict]) -> list[dict]:
    """Suivis de la rédaction (referentiel/suivis.csv), vérifiés contre le graphe."""
    if not TABLE_SUIVIS.exists():
        return []
    connus = {"driver": {p["k"] for p in pilotes}, "constructor": {c["k"] for c in constructeurs}}
    lignes, erreurs = [], []
    for l in _lire_csv(TABLE_SUIVIS):
        nature, ident = l["type"].strip(), l["identifiant"].strip()
        if nature not in connus:
            erreurs.append(f"type « {nature} » (driver ou constructor attendu)")
        elif ident not in connus[nature]:
            erreurs.append(f"{nature} « {ident} » inconnu du graphe")
        else:
            lignes.append({"nature": nature, "k": ident, "p": {"remarque": l.get("remarque") or None}})
    if erreurs:
        raise ComplementInvalide(f"{TABLE_SUIVIS.name} : {'; '.join(erreurs)}")
    return lignes
