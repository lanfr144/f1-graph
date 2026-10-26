# Graphe F1 — Neo4j

Base de données graphe des Grands Prix de Formule 1 (1950 à aujourd'hui), alimentée
depuis l'API publique [Jolpica-F1](https://github.com/jolpica/jolpica-f1), successeur
compatible de l'API Ergast.

**Seul ce que la source permet d'alimenter est modélisé.** Pas d'étiquette ni de
relation « pour plus tard » : un type vide laisserait croire à une donnée absente.

## En bref

```bash
cp .env.example .env
```

```bash
sh docker/preparer.sh && docker compose up -d --build
```

La pile Docker installe Neo4j, charge les 77 saisons (repris si interrompu), planifie les
deltas par cron (dimanche soir et lundi matin), sauvegarde la base chaque nuit avec une
rotation sur 7 jours, et sert une **interface web** : les seize questions de la rédaction avec
leurs requêtes, leurs réponses en tableaux, graphiques et graphes interactifs, un
explorateur de pilotes, le modèle et la santé du chargement. Chaque service a son
healthcheck ; la base survit à l'arrêt des conteneurs. Neo4j en édition Community ou
Enterprise, au choix (`NEO4J_EDITION`). Ports par défaut : 7475 (Browser), 7688 (Bolt),
8502 (interface), soit le port standard + 1. Exploitation, journaux et
dépannage : [docs/exploitation-docker.md](docs/exploitation-docker.md).

## Modèle

Description complète : [docs/modele-graphe.md](docs/modele-graphe.md), également
affichée, avec les volumes réels, par la page « Modèle du graphe » de l'interface.

- **Nœuds** : `Season`, `Circuit`, `Country:Nationality`, `Driver`, `Constructor`,
  `Status`, `Race`, `RaceResult`, `SprintResult`, `QualifyingResult`, `PitStop`, `LapTime`.
- **Pays et nationalités** : un seul nœud par code ISO 3166 alpha-3, porteur des deux
  étiquettes. « France » et « French » sont le même nœud `FRA`, nommé et qualifié en
  anglais comme en français. Les libellés de l'API sont traduits par
  [referentiel/pays.csv](referentiel/pays.csv), vérifié contre iso-codes.
- **Relations** : `IN_SEASON`, `HELD_AT`, `LOCATED_IN`, `HAS_NATIONALITY`, `IN_RACE`,
  `OF_DRIVER`, `FOR_CONSTRUCTOR`, `WITH_STATUS`, `DROVE_FOR {season}`, `RANKED_IN`, et
  `TEAMMATE_OF`, dérivée de `DROVE_FOR`, qui rend instantanées les recherches de chemins
  entre pilotes.
- **Absent, faute de source** : entraîneurs, directeurs d'équipe, académies, sponsors,
  dirigeants, fédération (voir la documentation du modèle).

## Schéma

| Fichier | Contenu | Édition |
|---|---|---|
| [schema/01_contraintes.cypher](schema/01_contraintes.cypher) | 16 contraintes d'unicité (nœuds, composite, relations) | Community et Enterprise, ≥ 5.7 |
| [schema/02_contraintes_enterprise.cypher](schema/02_contraintes_enterprise.cypher) | 87 contraintes d'existence et de type | Enterprise ≥ 5.9 |
| [schema/03_index.cypher](schema/03_index.cypher) | index range, point et plein texte (insensible aux accents) | ≥ 5.7 |
| [schema/04_requetes.cypher](schema/04_requetes.cypher) | requêtes de référence, une par index | documentation |

Sur Community, ce que Neo4j ne sait pas imposer (existence, cardinalité des relations)
est vérifié après chaque chargement par `charger.py`, qui se termine en erreur si un
invariant est violé.

### Neo4j Community : une seule base utilisateur

Community refuse `CREATE DATABASE` : le graphe F1 se charge alors dans la base `neo4j`,
éventuellement à côté d'autres graphes. C'est sans risque pour eux : le chargement ne
fait que des `MERGE` sur les étiquettes du modèle, et `--vider` n'efface que ces
étiquettes (liste `LABELS` de `charger.py`), jamais le reste de la base.

Essai de référence : Neo4j 2026.08.1 Community. Les 12 requêtes de
`04_requetes.cypher` y ont été profilées, et chacune emprunte l'index prévu.

## Utilisation

Prérequis : Python ≥ 3.11, Neo4j ≥ 5.7 (5.26 LTS ou 2025.x conseillés).

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

```bash
cp .env.example .env
```

### Tout en une commande, relançable : `pipeline.py`

```bash
.venv/Scripts/python pipeline.py --arrets-depuis 2011
```

Enchaîne référentiels, schéma, puis pour chaque saison extraction et chargement,
enfin contrôles d'invariants et manifeste. Chaque étape terminée est inscrite dans
`donnees/etat.json` : **après une interruption, relancer la même commande** reprend à
la première étape non faite, que l'arrêt vienne d'un Ctrl+C, d'une coupure réseau,
d'un processus tué ou de Neo4j indisponible. Une étape en échec est retentée à la
relance ; celles qui en dépendent sont marquées « bloquées », les autres continuent.

| Option | Effet |
|---|---|
| `--de 2020 --a 2024` | intervalle de saisons (défaut : toutes) |
| `--arrets-depuis 2011` | arrêts au stand à partir de cette saison (données depuis 2011) |
| `--tours-depuis 2024` | temps au tour (données depuis 1996 ; ~15 requêtes par course) |
| `--sans-extraction` | aucun accès réseau : charger le cache tel qu'il est |
| `--sans-chargement` | extraire seulement, sans toucher Neo4j |
| `--etat` | afficher l'avancement enregistré, sans rien exécuter |
| `--recommencer` | abandonner l'exécution inachevée et repartir de zéro |
| `--verbeux` | niveau DEBUG aussi à l'écran |

Traces, dans `donnees/journaux/` :

- `pipeline-AAAAMMJJ-HHMMSS.log` : journal complet de chaque exécution, niveau DEBUG,
  avec la trace Python de toute erreur ;
- `avancement.jsonl` : un événement JSON par début, fin, échec ou blocage d'étape,
  cumulé d'une exécution à l'autre (`etape`, `duree_s`, `requetes`, `refus_api`, `erreur`).

Codes de sortie : `0` succès, `1` étape en échec ou bloquée, `2` un autre traitement
utilise déjà `donnees/` (verrou), `130` interruption.

### Vérifier la base : `verifier.py`

```bash
.venv/Scripts/python verifier.py
```

En lecture seule : contraintes et index présents et `ONLINE`, invariants, puis
rapprochement **saison par saison** entre le cache (après transformation) et la base,
nombre par nombre (courses, résultats, qualifications, sprints, arrêts, tours,
`DROVE_FOR`, `RANKED_IN`). Chaque saison est déclarée complète, partielle (écarts
listés), absente de la base ou du cache. Suivent des contrôles métier : un vainqueur
par course disputée, un champion par saison close, victoires au classement cohérentes
avec les résultats chargés. Code de sortie 1 au moindre écart.

### Questions de la rédaction : `questions.py`

[requetes/questions.cypher](requetes/questions.cypher) répond, en Cypher, à seize
questions éditoriales transposées à la F1 (événement = Grand Prix, équipe = écurie,
coéquipiers = même écurie la même saison). Chacune indique sa couverture :
**complète**, **partielle** (la part que les données permettent, et ce qui manque)
ou **non couverte** : la source ne contient ni entraîneurs, ni académies, ni
sponsors, ni dirigeants, ni fédération, ni rédaction, et aucune relation n'est
inventée pour y suppléer.

```bash
.venv/Scripts/python questions.py --liste
```

```bash
.venv/Scripts/python questions.py 16 --param a="'alonso'" --param b="'hamilton'"
```

Les requêtes se collent aussi dans Neo4j Browser, après `:param nom => valeur` pour
chaque ligne `@param` du bloc.

### Étape par étape

1. **Extraire** vers le cache local `donnees/brut/` (rien n'est écrit dans Neo4j) :

   ```bash
   .venv/Scripts/python extraire.py
   ```

   Options : `--de 2011 --a 2024`, `--arrets`, `--tours`, `--forcer`. L'API limite à
   500 requêtes par heure : le script temporise seul ; ce qui est en cache n'est pas
   redemandé.

2. **Charger** (schéma, puis données, puis contrôles) :

   ```bash
   .venv/Scripts/python charger.py
   ```

   La transformation et la validation se font **avant** toute écriture : une donnée
   illisible ou une clé en double interrompt tout, sans charger à moitié.

3. **Tracer la provenance** :

   ```bash
   .venv/Scripts/python manifeste.py
   ```

`python transformer.py` valide le cache seul, sans Neo4j.

## Licences

Le **code** du projet (scripts, schéma, interface, configuration Docker) est publié
sous **GNU GPL v3** : voir [LICENSE](LICENSE).

Les **données** ne le sont pas : elles ne sont pas dans le dépôt et gardent leurs
propres licences, ci-dessous.

## Données et licence

Deux sources, aucune versionnée :

- **Jolpica-F1** (résultats) : CC BY-NC-SA 4.0 ;
- **iso-codes** du projet Debian (codes ISO 3166 et noms français des pays) :
  LGPL-2.1-or-later, version épinglée, téléchargée par le pipeline.


Les données Jolpica-F1 sont sous licence **CC BY-NC-SA 4.0** : usage non commercial,
attribution, partage dans les mêmes conditions. Elles ne sont **jamais versionnées**
(`donnees/` est exclu par `.gitignore`). [SOURCES.md](SOURCES.md), généré, en donne
la provenance, la licence relue dans les conditions de l'éditeur, et l'empreinte
SHA-256 de chaque réponse.
