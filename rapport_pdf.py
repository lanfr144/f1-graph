"""Réponses aux questions de la rédaction, en PDF.

    python questions.py --pdf reponses.pdf          # toutes les questions
    python questions.py 1 6 --pdf reponses.pdf      # certaines
    (et les boutons de téléchargement de la page « Questions » de l'interface)

Chaque question : son texte, l'explication en clair, la couverture, les valeurs trouvées
par les prérequêtes, la réponse complète, puis la requête Cypher exécutée. Une réponse
n'est jamais tronquée : un tableau trop large ou aux cellules trop longues (Q1, Q3…)
devient une suite de fiches. Les graphes interactifs de l'interface ne sont pas repris.

Les polices ne sont pas dans le dépôt : celles du système sont utilisées (paquet
fonts-dejavu-core dans l'image Docker, vérifié à la construction ; Arial et Consolas
sous Windows). Sans elles, PdfImpossible le dit : la police intégrée à reportlab perdrait
des caractères comme « œ », « ≥ » ou « → ».

L'attribution exigée par les licences des données figure en pied de chaque page.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

JEUX_DE_POLICES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/consola.ttf"),
]
ATTRIBUTION = ("Données : Jolpica-F1 (CC BY-NC-SA 4.0, usage non commercial) ; académies : contributeurs de "
               "Wikipédia (CC BY-SA 4.0) ; codes pays : iso-codes (LGPL-2.1-or-later).")
# Au-delà, un tableau devient illisible sur une page : une fiche par ligne.
COLONNES_MAX = 7
CELLULE_MAX = 90


class PdfImpossible(RuntimeError):
    pass


def polices() -> None:
    """Enregistre le premier jeu de polices complet ; échoue en nommant ce qui manque."""
    if "F1" in pdfmetrics.getRegisteredFontNames():
        return
    for normale, grasse, chasse in JEUX_DE_POLICES:
        if all(Path(f).exists() for f in (normale, grasse, chasse)):
            pdfmetrics.registerFont(TTFont("F1", normale))
            pdfmetrics.registerFont(TTFont("F1-Gras", grasse))
            pdfmetrics.registerFont(TTFont("F1-Mono", chasse))
            pdfmetrics.registerFontFamily("F1", normal="F1", bold="F1-Gras", italic="F1", boldItalic="F1-Gras")
            return
    raise PdfImpossible("aucune police adaptée pour le PDF ; cherchées : "
                        + ", ".join(j[0] for j in JEUX_DE_POLICES) + " (paquet fonts-dejavu-core sous Debian)")


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="F1", fontSize=9, leading=12)
    return {
        "base": base,
        "titre": ParagraphStyle("titre", parent=base, fontName="F1-Gras", fontSize=13, leading=17, spaceAfter=5),
        "section": ParagraphStyle("section", parent=base, fontName="F1-Gras", fontSize=10, leading=13,
                                  spaceBefore=8, spaceAfter=3, keepWithNext=1,
                                  textColor=colors.HexColor("#185FA5")),
        "note": ParagraphStyle("note", parent=base, fontSize=8, leading=10.5, textColor=colors.HexColor("#5F5E5A")),
        "cellule": ParagraphStyle("cellule", parent=base, fontSize=8, leading=10),
        "entete": ParagraphStyle("entete", parent=base, fontName="F1-Gras", fontSize=8, leading=10),
        "code": ParagraphStyle("code", parent=base, fontName="F1-Mono", fontSize=7, leading=9),
    }


def _texte(valeur) -> str:
    if valeur is None:
        return "—"
    if isinstance(valeur, (list, tuple)):
        return ", ".join(_texte(v) for v in valeur) or "—"
    return str(valeur)


def avec_valeurs(texte: str, params: dict) -> str:
    """« les $semaines semaines » devient « les 4 semaines » ; un paramètre inconnu reste écrit tel quel."""
    return re.sub(r"\$(\w+)", lambda m: _texte(params[m[1]]) if m[1] in params else m[0], texte)


def _p(texte, style) -> Paragraph:
    return Paragraph(escape(str(texte)), style)


def _code(cypher: str, style) -> Paragraph:
    lignes = []
    for ligne in cypher.splitlines():
        retrait = len(ligne) - len(ligne.lstrip())
        lignes.append("&nbsp;" * retrait + escape(ligne.lstrip()))
    return Paragraph("<br/>".join(lignes), style)


STYLE_TABLEAU = [
    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B4B2A9")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
]


def _reponse(colonnes: list[str], lignes: list[dict], largeur: float, st: dict) -> list:
    if not lignes:
        return [_p("Aucune ligne : la base ne contient pas de réponse pour ces paramètres.", st["base"])]
    textes = [[_texte(l.get(c)) for c in colonnes] for l in lignes]
    trop_long = any(len(t) > CELLULE_MAX for ligne in textes for t in ligne)
    if len(colonnes) > COLONNES_MAX or trop_long:
        return _fiches(colonnes, lignes, largeur, st)
    poids = [max(4, min(40, max([len(c)] + [len(ligne[i]) for ligne in textes]))) for i, c in enumerate(colonnes)]
    largeurs = [largeur * p / sum(poids) for p in poids]
    donnees = [[_p(c, st["entete"]) for c in colonnes]] + [[_p(t, st["cellule"]) for t in ligne] for ligne in textes]
    return [Table(donnees, colWidths=largeurs, repeatRows=1, style=TableStyle(
        STYLE_TABLEAU + [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6F1FB"))]))]


def _fiches(colonnes: list[str], lignes: list[dict], largeur: float, st: dict) -> list:
    """Une petite table « champ / valeur » par ligne ; une liste s'écrit un élément par ligne."""
    elements = []
    for i, ligne in enumerate(lignes, 1):
        rangees = []
        for c in colonnes:
            v = ligne.get(c)
            if isinstance(v, (list, tuple)) and v:
                corps = Paragraph("<br/>".join(escape(_texte(x)) for x in v), st["cellule"])
            else:
                corps = _p(_texte(v), st["cellule"])
            rangees.append([_p(c, st["entete"]), corps])
        elements += [_p(f"Ligne {i} sur {len(lignes)}", st["note"]),
                     Table(rangees, colWidths=[5 * cm, largeur - 5 * cm], splitInRow=1, style=TableStyle(
                         STYLE_TABLEAU + [("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E6F1FB"))])),
                     Spacer(1, 6)]
    return elements


class _CanevasNumerote(pdfcanvas.Canvas):
    """Pied de page « Page X sur Y » : le total n'est connu qu'à la fin du document."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        genere = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        for page in self._pages:
            self.__dict__.update(page)
            largeur = self._pagesize[0]
            self.setFont("F1", 7)
            self.setFillColor(colors.HexColor("#5F5E5A"))
            self.drawString(1.5 * cm, 1 * cm, ATTRIBUTION)
            self.drawRightString(largeur - 1.5 * cm, 1 * cm, f"Graphe F1, {genere} — page {self._pageNumber} sur {total}")
            super().showPage()
        super().save()


def construire(sections: list[dict], titre: str = "Graphe F1 — réponses aux questions de la rédaction") -> bytes:
    """`sections` : {numero, question, resultat (executer_question) ou None, erreur ou None}."""
    polices()
    st = _styles()
    tampon = io.BytesIO()
    format_page = landscape(A4)
    doc = SimpleDocTemplate(tampon, pagesize=format_page, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.6 * cm, title=titre, author="Graphe F1")
    largeur = format_page[0] - 3 * cm
    elements = []
    for rang, s in enumerate(sections):
        if rang:
            elements.append(PageBreak())
        q, r = s["question"], s.get("resultat")
        params = r["params"] if r else {}
        elements.append(_p(f"Q{s['numero']} — {q['titre']}", st["titre"]))
        if q.get("simple"):
            elements += [_p("En clair", st["section"]), _p(avec_valeurs(q["simple"], params), st["base"])]
        if q.get("notes"):
            elements += [_p("Couverture", st["section"]), _p(avec_valeurs(" ".join(q["notes"]), params), st["note"])]
        if s.get("erreur"):
            elements += [_p("Échec de la requête", st["section"]), _p(s["erreur"], st["base"])]
        if r:
            valeurs = [f"{k} = {_texte(v)}" for k, v in r["params"].items()]
            if valeurs:
                elements += [_p("Paramètres", st["section"]), _p(" ; ".join(valeurs), st["note"])]
            elements.append(_p(f"Réponse ({len(r['lignes'])} ligne(s))", st["section"]))
            elements += _reponse(r["colonnes"], r["lignes"], largeur, st)
            elements += [_p("Requête exécutée", st["section"]), _code(r["cypher"], st["code"])]
    doc.build(elements, canvasmaker=_CanevasNumerote)
    return tampon.getvalue()


def executer_sections(session, questions: dict, numeros: list[int], surcharges: dict | None = None) -> list[dict]:
    """Exécute les questions demandées. Une question en échec porte son erreur, sans arrêter les autres."""
    import questions as qmod
    sections = []
    for n in numeros:
        q = questions[n]
        section = {"numero": n, "question": q, "resultat": None, "erreur": None}
        if q["requete"]:
            try:
                section["resultat"] = qmod.executer_question(session, q, surcharges)
            except Exception as e:
                section["erreur"] = str(e)
        sections.append(section)
    return sections
