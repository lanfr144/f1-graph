# Plans d'exécution et index

> Tableau de mesure généré par `python plans.py --doc` — ne pas modifier à la main.

## Comment lire ce document

Avant d'exécuter une requête, Neo4j choisit un **plan** : l'ordre dans lequel il parcourt
le graphe. Deux commandes le montrent :

- `EXPLAIN` annonce le plan, sans exécuter la requête ;
- `PROFILE` exécute la requête et compte, pour chaque opérateur, ses **accès à la base**
  (*db hits*). C'est la vraie mesure du travail : plus il y en a, plus c'est lent.

Un **index** est comme l'index d'un livre : il évite de tout lire pour trouver une valeur.
Il ne sert donc que si le coût vient d'un parcours qui lit beaucoup pour garder peu. Il
ralentit aussi chaque écriture : on n'en pose que si la mesure montre un gain.

Pour voir ces plans : page « Questions » de l'interface, volet « Comprendre la requête » ;
ou `python plans.py 2 --detail`.

## Optimisations du 7 novembre 2026

Mesures avant/après sur la même base ; réponses comparées ligne à ligne, identiques.

| Requête | Avant (db hits) | Après (db hits) | Cause et remède |
|---|---:|---:|---|
| Q2, face-à-face | 102 634 435 | 170 464 | Motif : pour chaque paire, toute la carrière du second pilote était relue (30,8 millions de lignes). **Un index n'y pouvait rien** ; requête réécrite pour lire chaque carrière une fois, puis travailler course par course. De 40 s à moins d'une seconde. |
| Q7, duels contre les favoris | 15 211 038 | 500 907 | Même cause, même remède. |
| Q3, anciennes écuries | 49 386 | 40 906 | Index `drove_for_season` : la grille de la saison sans lire les 3 471 engagements. |
| Q9, transferts | 30 027 | 21 547 | Index `drove_for_season`. |
| Q11, prérequête | 9 156 | 676 | Index `drove_for_season`. |

## Ce qui n'appelle pas d'index

- Les parcours `NodeByLabelScan` restants lisent les 7 académies ou les 1 172 courses :
  lire tout est alors le bon plan (au plus 42 000 accès, quelques dizaines de ms).
- Q16 signale un « produit cartésien » : deux recherches par clé unique, une ligne chacune.
  L'avertissement de Neo4j est sans conséquence ici.

## Mesures actuelles

| Question | Requête | Lignes | Accès base (db hits) | Durée (ms) | Index utilisés | Parcours sans index |
|---|---|---:|---:|---:|---|---|
| Q1 | prérequête | 1 | 165 | 51 | NodeIndexSeekByRange | — |
| Q1 | requête | 4 | 38 710 | 151 | NodeIndexSeekByRange, NodeUniqueIndexSeek | — |
| Q2 | prérequête | 1 | 41 663 | 49 | NodeIndexSeekByRange | NodeByLabelScan (1172) |
| Q2 | requête | 25 | 170 464 | 839 | DirectedRelationshipIndexSeek | — |
| Q3 | prérequête | 1 | 41 663 | 47 | NodeIndexSeekByRange | NodeByLabelScan (1172) |
| Q3 | requête | 20 | 40 906 | 105 | DirectedRelationshipIndexSeek | — |
| Q4 | prérequête | 1 | 42 822 | 65 | — | NodeByLabelScan (1172) |
| Q4 | requête | 24 | 20 338 | 86 | NodeUniqueIndexSeek | — |
| Q5 | requête | 30 | 3 390 | 47 | — | NodeByLabelScan (7), NodeByLabelScan (7) |
| Q6 | prérequête | 1 | 7 | 10 | — | DirectedRelationshipTypeScan (3) |
| Q6 | requête | 3 | 288 | 54 | NodeIndexSeekByRange | DirectedRelationshipTypeScan (9) |
| Q7 | prérequête | 1 | 178 | 3 | NodeIndexScan | — |
| Q7 | requête | 15 | 500 907 | 449 | NodeIndexSeekByRange, NodeUniqueIndexSeek | — |
| Q9 | prérequête | 1 | 178 | 5 | NodeIndexScan | — |
| Q9 | requête | 8 | 21 547 | 32 | DirectedRelationshipIndexSeek | NodeByLabelScan (7), NodeByLabelScan (7) |
| Q10 | prérequête | 1 | 8 532 | 12 | — | NodeByLabelScan (214) |
| Q10 | requête | 1 | 162 272 | 84 | NodeUniqueIndexSeek | — |
| Q11 | prérequête | 1 | 676 | 4 | DirectedRelationshipIndexSeek, NodeIndexScan | — |
| Q11 | requête | 25 | 1 495 | 4 | NodeUniqueIndexSeek | — |
| Q12 | requête | 25 | 1 803 | 12 | — | NodeByLabelScan (7) |
| Q13 | requête | 20 | 118 703 | 156 | NodeIndexScan | NodeByLabelScan (7) |
| Q15 | requête | 6 | 1 590 | 23 | NodeUniqueIndexSeekByRange | — |
| Q16 | prérequête | 1 | 91 | 20 | NodeIndexScan, NodeUniqueIndexSeek | — |
| Q16 | requête | 1 | 286 | 22 | NodeUniqueIndexSeek | — |

Total : 1 218 674 accès à la base.

## Usage des index

Les index peu lus servent les requêtes de référence de `schema/04_requetes.cypher` (recherche par nom, distance, palmarès), pas les seize questions.

| Index | Type | Lectures depuis le démarrage de Neo4j |
|---|---|---:|
| `race_season` | RANGE | 2 383 |
| `race_date` | RANGE | 173 |
| `drove_for_season` | RANGE | 24 |
| `circuit_location` | POINT | 0 |
| `circuit_name_search` | FULLTEXT | 0 |
| `constructor_name_search` | FULLTEXT | 0 |
| `country_name_search` | FULLTEXT | 0 |
| `driver_name_search` | FULLTEXT | 0 |
| `pit_stop_duration` | RANGE | 0 |
| `race_result_position` | RANGE | 0 |
| `ranked_in_position` | RANGE | 0 |
