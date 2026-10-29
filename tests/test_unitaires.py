"""Tests unitaires, sans réseau ni Neo4j : exécutés à la construction de l'image.

    python -m unittest tests.test_unitaires
"""
import csv
import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import complements  # noqa: E402
import questions  # noqa: E402
import transformer as tr  # noqa: E402
from charger import instructions  # noqa: E402


class LectureWikipedia(unittest.TestCase):
    """Cas rencontrés dans les pages des académies (révisions d'octobre 2026)."""

    TABLEAU = """
== Graduates to Formula One ==
{| class="wikitable"
! Driver
! Academy experience
! F1 experience with other teams
! Years
|-
| {{flagicon|MON}} [[Charles Leclerc]]<ref name="x">source</ref>
|align=center| 2016–2018
| ''[[Sauber]] ({{F1|2018}})''
| {{F1|2019}}–
|-
| {{sortname|Oliver|Bearman}}
| 2022–
| {{N/A}}
| {{F1|2024}}
|}
== Esports ==
{| class="wikitable"
! Driver !! Years
|-
| Bardia Broumand || 2023–
|}
"""

    def test_periodes(self):
        self.assertEqual(complements.periodes("2010–2013"), [(2010, 2013)])
        self.assertEqual(complements.periodes("2023–"), [(2023, None)])
        self.assertEqual(complements.periodes("2015–16, 2019"), [(2015, 2016), (2019, 2019)])
        self.assertEqual(complements.periodes("2004&ndash;2005"), [(2004, 2005)])
        self.assertEqual(complements.periodes("None"), [])

    def test_tableaux_et_liens(self):
        t = complements.tableaux(self.TABLEAU)
        self.assertEqual(len(t), 2)
        self.assertEqual(t[0]["section"], "Graduates to Formula One")
        self.assertEqual(t[0]["entetes"], ["Driver", "Academy experience", "F1 experience with other teams", "Years"])
        self.assertEqual(complements.premier_lien(t[0]["lignes"][0][0]), "Charles Leclerc")
        self.assertEqual(t[0]["lignes"][0][1], "2016–2018")  # attribut « align=center| » retiré
        self.assertEqual(complements.premier_lien(t[0]["lignes"][1][0]), "Oliver Bearman")  # {{sortname}}

    def test_titre_de_url(self):
        self.assertEqual(complements.titre_de_url("http://en.wikipedia.org/wiki/Nico_H%C3%BClkenberg"),
                         "Nico Hülkenberg")
        self.assertIsNone(complements.titre_de_url(None))

    def test_table_des_academies(self):
        with (RACINE / "referentiel" / "academies.csv").open(encoding="utf-8") as f:
            lignes = list(csv.DictReader(f, delimiter=";"))
        self.assertEqual(len({l["academyId"] for l in lignes}), len(lignes))
        for l in lignes:
            self.assertRegex(l["academyId"], r"^[a-z_]+$")
            self.assertTrue(l["page_wikipedia"] and l["ecuries"], l)

    def test_chaque_question_couverte_est_expliquee(self):
        for n, q in questions.lire_questions().items():
            with self.subTest(question=n):
                if q["requete"]:
                    self.assertTrue(q["etapes"], "requête sans étapes @etape d'explication")
                    for e in q["etapes"]:
                        self.assertTrue(e["titre"] and e["motif"], e)


class Conversions(unittest.TestCase):
    def test_chronos(self):
        self.assertEqual(tr.chrono_ms("1:31:44.742", "t"), 5504742)
        self.assertEqual(tr.chrono_ms("1:32.608", "t"), 92608)
        self.assertEqual(tr.chrono_ms("25.208", "t"), 25208)
        self.assertIsNone(tr.chrono_ms("", "t"))
        with self.assertRaises(tr.DonneeInvalide):
            tr.chrono_ms("abandon", "t")

    def test_absences_de_la_source(self):
        # L'API publie parfois le texte "None" pour une absence (forfaits 1961-1963).
        for absent in (None, "", "None", "null"):
            self.assertIsNone(tr.entier(absent, "t"))
        with self.assertRaises(tr.DonneeInvalide):
            tr.entier("douze", "t")

    def test_cle_de_resultat(self):
        self.assertEqual(tr.cle_resultat("1954-02", "14", "vukovich", "r"), "1954-02-14-vukovich")
        self.assertEqual(tr.cle_resultat("1961-04", "None", "bordeu", "r"), "1961-04-sans-numero-bordeu")

    def test_horodatage_sans_fuseau_refuse(self):
        with self.assertRaises(tr.DonneeInvalide):
            tr.instant("2024-03-02", "15:00:00", "t")


class ReferentielPays(unittest.TestCase):
    def setUp(self):
        self.lignes = list(csv.DictReader((RACINE / "referentiel" / "pays.csv").open(encoding="utf-8"),
                                          delimiter=";"))

    def test_format(self):
        for l in self.lignes:
            self.assertIn(l["role"], ("pays", "nationalite"), l)
            self.assertRegex(l["iso3"], r"^[A-Z]{3}$", l)
            if l["role"] == "nationalite":
                self.assertTrue(l["nationalite_fr"], f"gentilé français manquant : {l}")

    def test_libelles_uniques(self):
        cles = [(l["role"], l["libelle_source"]) for l in self.lignes]
        self.assertEqual(len(cles), len(set(cles)))

    def test_une_nationalite_par_code(self):
        # Un nœud ISO porte UN gentilé : deux libellés de nationalité sur un même code
        # rendraient la propriété `nationality` ambiguë.
        codes = [l["iso3"] for l in self.lignes if l["role"] == "nationalite"]
        self.assertEqual(len(codes), len(set(codes)))


class Fichiers(unittest.TestCase):
    def test_schema_lisible(self):
        for f in sorted((RACINE / "schema").glob("0[0-3]_*.cypher")):
            with self.subTest(fichier=f.name):
                self.assertTrue(instructions(f))

    def test_seize_questions(self):
        qs = questions.lire_questions()
        self.assertEqual(sorted(qs), list(range(1, 17)))
        for n, q in qs.items():
            with self.subTest(question=n):
                note = " ".join(q["notes"])
                self.assertTrue(q["requete"] or re.search("NON COUVERTE|Doublon", note),
                                "ni requête ni couverture déclarée")
                for nom in re.findall(r"\$(\w+)", q["requete"]):
                    fournis = set(q["params"]) | {c for p in q["prerequetes"]
                                                  for c in re.findall(r"\bAS (\w+)", p["cypher"].split("RETURN")[-1])}
                    self.assertIn(nom, fournis, f"paramètre ${nom} jamais fourni")


if __name__ == "__main__":
    unittest.main()
