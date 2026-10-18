"""Génère .env.example à partir de .env : même contenu, secrets remplacés.

    python docker/env_exemple.py

Toute variable dont le nom évoque un secret (PASSWORD, SECRET, TOKEN, KEY…) reçoit
la valeur factice « password_<NOM_DE_LA_VARIABLE> » ; le reste (ports, chemins,
planifications, commentaires) est recopié tel quel. docker/preparer.sh refuse de
démarrer tant qu'une valeur commence encore par « password_ ».
"""
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SECRET = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|PASSPHRASE|API_KEY|_KEY$)", re.I)


def main() -> int:
    source, cible = RACINE / ".env", RACINE / ".env.example"
    if not source.exists():
        print(f"{source} absent : rien à générer", file=sys.stderr)
        return 1
    lignes, masques = [], []
    for ligne in source.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ligne)
        if m and SECRET.search(m[1]):
            lignes.append(f"{m[1]}=password_{m[1]}")
            masques.append(m[1])
        else:
            lignes.append(ligne)
    entete = ["# Modèle généré par `python docker/env_exemple.py` à partir de .env — ne pas modifier",
              "# à la main. Copier en .env, puis remplacer chaque valeur « password_… ».", ""]
    cible.write_text("\n".join(entete + lignes) + "\n", encoding="utf-8", newline="\n")
    print(f"{cible.name} : {len(lignes)} ligne(s), secret(s) masqué(s) : {', '.join(masques) or 'aucun'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
