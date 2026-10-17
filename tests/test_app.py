"""Tests d'intégration de l'interface web : chaque page, chaque question, sans navigateur.

Exigent une base Neo4j chargée (variables NEO4J_*). Lancés par le service `tests`
de compose.yaml, ou : python -m unittest tests.test_app
"""
import os
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "app"))

from streamlit.testing.v1 import AppTest  # noqa: E402

import questions  # noqa: E402

PAGES = RACINE / "app" / "pages"
DELAI = int(os.environ.get("F1_TEST_DELAI_S", "120"))


class PagesWeb(unittest.TestCase):
    def executer(self, page: str, **selections) -> AppTest:
        at = AppTest.from_file(str(PAGES / page), default_timeout=DELAI).run()
        for index, valeur in selections.items():
            at.selectbox[int(index[1:])].set_value(valeur).run()
        self.assertFalse(at.exception, f"{page} {selections} : {[e.message for e in at.exception]}")
        self.assertFalse(at.error, f"{page} {selections} : {[e.value for e in at.error]}")
        return at

    def test_chaque_question(self):
        for n in sorted(questions.lire_questions()):
            with self.subTest(question=n):
                self.executer("questions.py", s0=n)

    def test_pilote(self):
        at = self.executer("pilote.py")
        self.assertTrue(at.metric, "fiche pilote sans indicateurs")

    def test_modele(self):
        self.executer("modele.py")

    def test_sante(self):
        self.executer("sante.py")


if __name__ == "__main__":
    unittest.main()
