# Explication des requêtes

> Généré par `python questions.py --doc` à partir des lignes `@etape` de
> `requetes/questions.cypher` — ne pas modifier à la main.

Chaque question est décomposée en étapes : ce que l'étape **parcourt** dans le graphe,
puis les **filtres** appliqués (`WHERE`, `LIMIT`, comparaisons). L'interface web
(page « Questions ») montre en plus le **plan d'exécution** réel de Neo4j.

## Q1 — What recent event has left its mark on the world of F1 over the last few weeks? Who took part in the races during this event, and what were the results?

Couverture : complète. Fenêtre : les $semaines semaines qui précèdent le dernier Grand Prix disputé, jusqu'à aujourd'hui — elle s'allonge d'elle-même pendant l'intersaison. Les Grands Prix de la fenêtre sont classés par nombre de faits marquants (première victoire, victoire partie loin, changement de leader au championnat, hécatombe d'abandons), puis du plus récent au plus ancien : la première ligne est l'événement qui a le plus marqué.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Fenêtre de temps | `(prérequête) Race` | date ≤ aujourd'hui ET au moins un RaceResult ; dernier = max(date) ; début = dernier − $semaines semaines |
| 2. Grands Prix de la fenêtre | `(Race)-[:HELD_AT]->(Circuit)` | $debut ≤ date ≤ $fin ET course disputée (EXISTS RaceResult) |
| 3. Vainqueur | `(Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]->(Driver)` | position = 1 |
| 4. Leader avant et après | `sous-requête : (Driver)<-[:OF_DRIVER]-(résultat)-[:IN_RACE]->(Race de la même saison)` | RaceResult OU SprintResult ; manche ≤ manche courante ; somme des points, tri décroissant, premier |
| 5. Faits marquants | `vainqueur, grille, abandons` | aucune victoire antérieure du vainqueur ; grille ≥ $depart_lointain ; leader avant ≠ leader après ; non classés ≥ $abandons_nombreux |
| 6. Participants et classement | `(Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER, FOR_CONSTRUCTOR, WITH_STATUS]` | tri par position ; puis Grands Prix triés par nombre de faits, puis date décroissante |

```mermaid
flowchart TD
  E1["<b>1. Fenêtre de temps</b><br/>(prérequête) Race<br/><i>date ≤ aujourd'hui ET au moins un RaceResult ; dernier = max(date) ; début = dernier − $semaines semaines</i>"]
  E2["<b>2. Grands Prix de la fenêtre</b><br/>(Race)-[:HELD_AT]-#gt;(Circuit)<br/><i>$debut ≤ date ≤ $fin ET course disputée (EXISTS RaceResult)</i>"]
  E1 --> E2
  E3["<b>3. Vainqueur</b><br/>(Race)#lt;-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]-#gt;(Driver)<br/><i>position = 1</i>"]
  E2 --> E3
  E4["<b>4. Leader avant et après</b><br/>sous-requête : (Driver)#lt;-[:OF_DRIVER]-(résultat)-[:IN_RACE]-#gt;(Race de la même saison)<br/><i>RaceResult OU SprintResult ; manche ≤ manche courante ; somme des points, tri décroissant, premier</i>"]
  E3 --> E4
  E5["<b>5. Faits marquants</b><br/>vainqueur, grille, abandons<br/><i>aucune victoire antérieure du vainqueur ; grille ≥ $depart_lointain ; leader avant ≠ leader après ; non classés ≥ $abandons_nombreux</i>"]
  E4 --> E5
  E6["<b>6. Participants et classement</b><br/>(Race)#lt;-[:IN_RACE]-(RaceResult)-[:OF_DRIVER, FOR_CONSTRUCTOR, WITH_STATUS]<br/><i>tri par position ; puis Grands Prix triés par nombre de faits, puis date décroissante</i>"]
  E5 --> E6
```

## Q2 — Which opponents are facing each other again, and what is their head-to-head record?

Couverture : complète, à une approximation près : l'API ne publie pas la liste des engagés d'une course future ; la grille retenue est celle de la saison de la prochaine course (ou de la dernière, pendant l'intersaison). Face-à-face = courses disputées par les deux ; devant = mieux classé (abandons compris).

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Course de référence | `(prérequête) Race` | prochaine course : date ≥ aujourd'hui SANS résultat, tri par date, LIMIT 1 ; à défaut la dernière disputée |
| 2. Grille | `(Driver)-[:DROVE_FOR]->(Constructor)` | DROVE_FOR.season = $saison_grille |
| 3. Paires d'adversaires | `grille × grille` | a.driverId < b.driverId (chaque paire une fois) ; $a, $b s'ils sont donnés |
| 4. Courses communes | `(a)<-[:OF_DRIVER]-(RaceResult)-[:IN_RACE]->(Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]->(b)` | date de la course < $date_ref |
| 5. Bilan | `comptage par paire` | devant = position inférieure ; tri par nombre de courses communes ; LIMIT 25 |

```mermaid
flowchart TD
  E1["<b>1. Course de référence</b><br/>(prérequête) Race<br/><i>prochaine course : date ≥ aujourd'hui SANS résultat, tri par date, LIMIT 1 ; à défaut la dernière disputée</i>"]
  E2["<b>2. Grille</b><br/>(Driver)-[:DROVE_FOR]-#gt;(Constructor)<br/><i>DROVE_FOR.season = $saison_grille</i>"]
  E1 --> E2
  E3["<b>3. Paires d'adversaires</b><br/>grille × grille<br/><i>a.driverId #lt; b.driverId (chaque paire une fois) ; $a, $b s'ils sont donnés</i>"]
  E2 --> E3
  E4["<b>4. Courses communes</b><br/>(a)#lt;-[:OF_DRIVER]-(RaceResult)-[:IN_RACE]-#gt;(Race)#lt;-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]-#gt;(b)<br/><i>date de la course #lt; $date_ref</i>"]
  E3 --> E4
  E5["<b>5. Bilan</b><br/>comptage par paire<br/><i>devant = position inférieure ; tri par nombre de courses communes ; LIMIT 25</i>"]
  E4 --> E5
```

## Q3 — Which participants are facing a former team or former teammates?

Couverture : complète. Pour chaque pilote de la grille retenue : ses anciennes écuries encore engagées contre lui, et ses anciens coéquipiers désormais dans une autre écurie que la sienne.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Course de référence | `(prérequête) Race` | comme Q2 : prochaine course, à défaut la dernière disputée |
| 2. Pilote et écurie actuelle | `(Driver)-[:DROVE_FOR]->(Constructor)` | DROVE_FOR.season = $saison_grille |
| 3. Anciennes écuries adverses | `(Driver)-[:DROVE_FOR]->(Constructor)` | saison < $saison_grille ; écurie ≠ actuelle ; écurie engagée cette saison (EXISTS DROVE_FOR $saison_grille) |
| 4. Anciens coéquipiers adverses | `(Driver)-[:DROVE_FOR]->(Constructor)<-[:DROVE_FOR]-(Driver)` | même saison ; saison < $saison_grille ; coéquipier engagé cette saison ; PAS dans l'écurie actuelle |
| 5. Résultat | `une ligne par pilote` | au moins une ancienne écurie OU un ancien coéquipier adverse |

```mermaid
flowchart TD
  E1["<b>1. Course de référence</b><br/>(prérequête) Race<br/><i>comme Q2 : prochaine course, à défaut la dernière disputée</i>"]
  E2["<b>2. Pilote et écurie actuelle</b><br/>(Driver)-[:DROVE_FOR]-#gt;(Constructor)<br/><i>DROVE_FOR.season = $saison_grille</i>"]
  E1 --> E2
  E3["<b>3. Anciennes écuries adverses</b><br/>(Driver)-[:DROVE_FOR]-#gt;(Constructor)<br/><i>saison #lt; $saison_grille ; écurie ≠ actuelle ; écurie engagée cette saison (EXISTS DROVE_FOR $saison_grille)</i>"]
  E2 --> E3
  E4["<b>4. Anciens coéquipiers adverses</b><br/>(Driver)-[:DROVE_FOR]-#gt;(Constructor)#lt;-[:DROVE_FOR]-(Driver)<br/><i>même saison ; saison #lt; $saison_grille ; coéquipier engagé cette saison ; PAS dans l'écurie actuelle</i>"]
  E3 --> E4
  E5["<b>5. Résultat</b><br/>une ligne par pilote<br/><i>au moins une ancienne écurie OU un ancien coéquipier adverse</i>"]
  E4 --> E5
```

## Q4 — Who has moved up or down in the rankings since the previous week?

Couverture : complète pour la saison en cours. « Semaine précédente » = manche précédente. Le classement est recalculé (points de course et de sprint cumulés) : l'API ne publie que le classement après la dernière manche, rapporté en regard (rang_officiel) pour contrôle. Égalité de points : départage au nombre de meilleures places en Grand Prix (victoires, puis deuxièmes places…), arrivées classées seulement. Avant 1991, les résultats décomptés font diverger ce calcul.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Saison | `(prérequête) Race` | course disputée ; saisons d'au moins 2 manches ; la plus récente |
| 2. Deux manches comparées | `Race de la saison` | dernière manche disputée, et la précédente |
| 3. Points cumulés | `(Driver)<-[:OF_DRIVER]-(résultat)-[:IN_RACE]->(Race)` | RaceResult OU SprintResult ; manche ≤ manche comparée |
| 4. Classement | `tri` | points décroissants, puis nombre de victoires, de 2es places… (positions classées seulement) |
| 5. Évolution | `rang avant − rang après` | rang officiel lu dans RANKED_IN si afterRound = dernière manche |

```mermaid
flowchart TD
  E1["<b>1. Saison</b><br/>(prérequête) Race<br/><i>course disputée ; saisons d'au moins 2 manches ; la plus récente</i>"]
  E2["<b>2. Deux manches comparées</b><br/>Race de la saison<br/><i>dernière manche disputée, et la précédente</i>"]
  E1 --> E2
  E3["<b>3. Points cumulés</b><br/>(Driver)#lt;-[:OF_DRIVER]-(résultat)-[:IN_RACE]-#gt;(Race)<br/><i>RaceResult OU SprintResult ; manche ≤ manche comparée</i>"]
  E2 --> E3
  E4["<b>4. Classement</b><br/>tri<br/><i>points décroissants, puis nombre de victoires, de 2es places… (positions classées seulement)</i>"]
  E3 --> E4
  E5["<b>5. Évolution</b><br/>rang avant − rang après<br/><i>rang officiel lu dans RANKED_IN si afterRound = dernière manche</i>"]
  E4 --> E5
```

## Q5 — Which athletes have had the same coach, and during the same period?

Couverture : complète, par substitution. « Même entraîneur » = même ACADÉMIE de pilotes (Wikipédia) ; « même période » = années d'adhésion qui se chevauchent. Une adhésion en cours compte jusqu'à l'année courante. Les coéquipiers (même écurie, même saison) sont l'autre équivalent : relation TEAMMATE_OF, question 16.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Adhésions | `(Driver)-[:MEMBER_OF]->(Academy)<-[:MEMBER_OF]-(Driver)` | a.driverId < b.driverId (chaque paire une fois) |
| 2. Période commune | `années de début et de fin` | début commun = max(débuts) ; fin commune = min(fins, en cours = année courante) ; début commun ≤ fin commune |
| 3. Résultat | `une ligne par paire et académie` | tri par durée commune décroissante ; LIMIT 30 |

```mermaid
flowchart TD
  E1["<b>1. Adhésions</b><br/>(Driver)-[:MEMBER_OF]-#gt;(Academy)#lt;-[:MEMBER_OF]-(Driver)<br/><i>a.driverId #lt; b.driverId (chaque paire une fois)</i>"]
  E2["<b>2. Période commune</b><br/>années de début et de fin<br/><i>début commun = max(débuts) ; fin commune = min(fins, en cours = année courante) ; début commun ≤ fin commune</i>"]
  E1 --> E2
  E3["<b>3. Résultat</b><br/>une ligne par paire et académie<br/><i>tri par durée commune décroissante ; LIMIT 30</i>"]
  E2 --> E3
```

## Q6 — Which upcoming events involve participants followed by the newsroom?

Couverture : complète, dès que la rédaction renseigne referentiel/suivis.csv (pilotes ou écuries qu'elle suit). Sans suivi déclaré, la réponse est vide : rien n'est deviné. Engagés d'une course future = pilotes et écuries de sa saison, l'API ne publiant pas la liste des engagés.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Suivis | `(prérequête) (Newsroom)-[:FOLLOWS]->(Driver ou Constructor)` | comptage : 0 = referentiel/suivis.csv vide |
| 2. Prochaines courses | `Race` | date ≥ aujourd'hui ET aucun résultat ; tri par date ; LIMIT $prochaines |
| 3. Suivis engagés | `(Newsroom)-[:FOLLOWS]->(x)` | pilote : DROVE_FOR de la saison de la course ; écurie : au moins un pilote engagé cette saison |
| 4. Résultat | `une ligne par course` | au moins un suivi engagé ; tri par date |

```mermaid
flowchart TD
  E1["<b>1. Suivis</b><br/>(prérequête) (Newsroom)-[:FOLLOWS]-#gt;(Driver ou Constructor)<br/><i>comptage : 0 = referentiel/suivis.csv vide</i>"]
  E2["<b>2. Prochaines courses</b><br/>Race<br/><i>date ≥ aujourd'hui ET aucun résultat ; tri par date ; LIMIT $prochaines</i>"]
  E1 --> E2
  E3["<b>3. Suivis engagés</b><br/>(Newsroom)-[:FOLLOWS]-#gt;(x)<br/><i>pilote : DROVE_FOR de la saison de la course ; écurie : au moins un pilote engagé cette saison</i>"]
  E2 --> E3
  E4["<b>4. Résultat</b><br/>une ligne par course<br/><i>au moins un suivi engagé ; tri par date</i>"]
  E3 --> E4
```

## Q7 — Who has performed best against the highest-ranked opponents at the time of the match?

Couverture : complète. « Les mieux classés au moment du match » = les $top premiers au championnat recalculé avant la course (manches précédentes de la saison). Duel gagné = arrivée devant l'un d'eux. Première manche exclue (pas encore de classement). Un pilote doit compter au moins $duels_min duels.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Période | `(prérequête) Race` | les cinq dernières saisons disputées |
| 2. Courses | `Race` | $de ≤ saison ≤ $a ; manche > 1 ; course disputée |
| 3. Favoris au départ | `sous-requête : points cumulés AVANT la course` | manches < manche courante ; tri décroissant ; LIMIT $top |
| 4. Duels | `(Race)<-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]->(Driver) × favoris` | favori ≠ pilote lui-même ; duel gagné = position < position du favori |
| 5. Résultat | `par pilote` | duels ≥ $duels_min ; tri par % de duels gagnés ; LIMIT 15 |

```mermaid
flowchart TD
  E1["<b>1. Période</b><br/>(prérequête) Race<br/><i>les cinq dernières saisons disputées</i>"]
  E2["<b>2. Courses</b><br/>Race<br/><i>$de ≤ saison ≤ $a ; manche #gt; 1 ; course disputée</i>"]
  E1 --> E2
  E3["<b>3. Favoris au départ</b><br/>sous-requête : points cumulés AVANT la course<br/><i>manches #lt; manche courante ; tri décroissant ; LIMIT $top</i>"]
  E2 --> E3
  E4["<b>4. Duels</b><br/>(Race)#lt;-[:IN_RACE]-(RaceResult)-[:OF_DRIVER]-#gt;(Driver) × favoris<br/><i>favori ≠ pilote lui-même ; duel gagné = position #lt; position du favori</i>"]
  E3 --> E4
  E5["<b>5. Résultat</b><br/>par pilote<br/><i>duels ≥ $duels_min ; tri par % de duels gagnés ; LIMIT 15</i>"]
  E4 --> E5
```

## Q8 — Which participants are facing a former team or former teammates?

Doublon de la question 3 : même requête, voir Q3.

## Q9 — What transfers or coaching changes have been announced, and when do they take effect?

Couverture : PARTIELLE. Pas de dates d'annonce dans les sources : seuls les changements EFFECTIFS sont connus. Transferts : nouvelle écurie, datée par la première course disputée avec elle. Changements d'encadrement : entrées dans une académie l'année $saison et sorties à la fin de l'année précédente (Wikipédia, à l'année près).

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Saison | `(prérequête) Race` | dernière saison disputée |
| 2. Transferts | `(Driver)-[:DROVE_FOR]->(Constructor)` | DROVE_FOR.season = $saison ET pas de DROVE_FOR vers cette écurie en $saison − 1 |
| 3. Date d'effet du transfert | `(Driver)<-[:OF_DRIVER]-(résultat)-[:FOR_CONSTRUCTOR]->(nouvelle écurie)` | course de $saison ; tri par date ; LIMIT 1 |
| 4. Entrées en académie | `(Driver)-[:MEMBER_OF]->(Academy)` | fromYear = $saison |
| 5. Sorties d'académie | `(Driver)-[:MEMBER_OF]->(Academy)` | toYear = $saison − 1 |
| 6. Résultat | `UNION ALL des trois listes` | tri par date d'effet |

```mermaid
flowchart TD
  E1["<b>1. Saison</b><br/>(prérequête) Race<br/><i>dernière saison disputée</i>"]
  E2["<b>2. Transferts</b><br/>(Driver)-[:DROVE_FOR]-#gt;(Constructor)<br/><i>DROVE_FOR.season = $saison ET pas de DROVE_FOR vers cette écurie en $saison − 1</i>"]
  E1 --> E2
  E3["<b>3. Date d'effet du transfert</b><br/>(Driver)#lt;-[:OF_DRIVER]-(résultat)-[:FOR_CONSTRUCTOR]-#gt;(nouvelle écurie)<br/><i>course de $saison ; tri par date ; LIMIT 1</i>"]
  E2 --> E3
  E4["<b>4. Entrées en académie</b><br/>(Driver)-[:MEMBER_OF]-#gt;(Academy)<br/><i>fromYear = $saison</i>"]
  E3 --> E4
  E5["<b>5. Sorties d'académie</b><br/>(Driver)-[:MEMBER_OF]-#gt;(Academy)<br/><i>toYear = $saison − 1</i>"]
  E4 --> E5
  E6["<b>6. Résultat</b><br/>UNION ALL des trois listes<br/><i>tri par date d'effet</i>"]
  E5 --> E6
```

## Q10 — If a coach is removed from the network, which players or groups become disconnected?

Couverture : PARTIELLE, par analogie. L'encadrement retenu est l'ÉCURIE : la retirer coupe du réseau des coéquipiers les pilotes qui n'ont couru que pour elle, et défait les binômes qu'elle seule réunissait. Les académies ne relient pas les pilotes entre eux dans ce réseau : les retirer n'isolerait personne.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Écurie retirée | `(prérequête) (Driver)-[:DROVE_FOR]->(Constructor)` | pilotes n'ayant couru que pour UNE écurie ; l'écurie qui en compte le plus |
| 2. Pilotes isolés | `(Driver)-[:DROVE_FOR]->(écurie)` | AUCUN DROVE_FOR vers une autre écurie |
| 3. Binômes défaits | `(a)-[:DROVE_FOR]->(écurie)<-[:DROVE_FOR]-(b)` | même saison ; a.driverId < b.driverId ; jamais coéquipiers dans une autre écurie |

```mermaid
flowchart TD
  E1["<b>1. Écurie retirée</b><br/>(prérequête) (Driver)-[:DROVE_FOR]-#gt;(Constructor)<br/><i>pilotes n'ayant couru que pour UNE écurie ; l'écurie qui en compte le plus</i>"]
  E2["<b>2. Pilotes isolés</b><br/>(Driver)-[:DROVE_FOR]-#gt;(écurie)<br/><i>AUCUN DROVE_FOR vers une autre écurie</i>"]
  E1 --> E2
  E3["<b>3. Binômes défaits</b><br/>(a)-[:DROVE_FOR]-#gt;(écurie)#lt;-[:DROVE_FOR]-(b)<br/><i>même saison ; a.driverId #lt; b.driverId ; jamais coéquipiers dans une autre écurie</i>"]
  E2 --> E3
```

## Q11 — Which players are indirectly connected through their career paths, without having attended the same academy or shared a coach?

Couverture : complète, par substitution. Reliés indirectement = un coéquipier commun (TEAMMATE_OF à deux pas). Exclus : les pilotes déjà coéquipiers (même encadrement d'écurie) et ceux passés par une même académie, à n'importe quelle époque.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Pilote de départ | `(prérequête) (Driver)-[:DROVE_FOR]->(Constructor)` | grille de la dernière saison ; le plus de coéquipiers distincts |
| 2. Deux pas de coéquipiers | `(a)-[:TEAMMATE_OF]-(m)-[:TEAMMATE_OF]-(b)` | b ≠ a |
| 3. Pas d'encadrement commun | `NOT EXISTS (a)-[:TEAMMATE_OF]-(b)` | jamais coéquipiers |
| 4. Pas d'académie commune | `NOT EXISTS (a)-[:MEMBER_OF]->(Academy)<-[:MEMBER_OF]-(b)` | aucune académie en commun |
| 5. Résultat | `par pilote relié` | intermédiaires collectés ; tri par nombre d'intermédiaires ; LIMIT 25 |

```mermaid
flowchart TD
  E1["<b>1. Pilote de départ</b><br/>(prérequête) (Driver)-[:DROVE_FOR]-#gt;(Constructor)<br/><i>grille de la dernière saison ; le plus de coéquipiers distincts</i>"]
  E2["<b>2. Deux pas de coéquipiers</b><br/>(a)-[:TEAMMATE_OF]-(m)-[:TEAMMATE_OF]-(b)<br/><i>b ≠ a</i>"]
  E1 --> E2
  E3["<b>3. Pas d'encadrement commun</b><br/>NOT EXISTS (a)-[:TEAMMATE_OF]-(b)<br/><i>jamais coéquipiers</i>"]
  E2 --> E3
  E4["<b>4. Pas d'académie commune</b><br/>NOT EXISTS (a)-[:MEMBER_OF]-#gt;(Academy)#lt;-[:MEMBER_OF]-(b)<br/><i>aucune académie en commun</i>"]
  E3 --> E4
  E5["<b>5. Résultat</b><br/>par pilote relié<br/><i>intermédiaires collectés ; tri par nombre d'intermédiaires ; LIMIT 25</i>"]
  E4 --> E5
```

## Q12 — Which coaches connect players from different academies?

Couverture : complète, par substitution. « Entraîneur » = encadrement de course : l'ÉCURIE D'UNE SAISON. Elle relie des académies quand elle fait courir, la même saison, des pilotes formés dans des académies différentes (adhésion commencée avant ou pendant cette saison).

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Pilotes engagés | `(Driver)-[:DROVE_FOR]->(Constructor)` | toutes saisons |
| 2. Formation | `(Driver)-[:MEMBER_OF]->(Academy)` | année d'entrée ≤ saison de l'engagement |
| 3. Écurie-saison | `regroupement par écurie et saison` | au moins 2 académies DIFFÉRENTES |
| 4. Résultat | `une ligne par écurie-saison` | tri par nombre d'académies, puis saison décroissante ; LIMIT 25 |

```mermaid
flowchart TD
  E1["<b>1. Pilotes engagés</b><br/>(Driver)-[:DROVE_FOR]-#gt;(Constructor)<br/><i>toutes saisons</i>"]
  E2["<b>2. Formation</b><br/>(Driver)-[:MEMBER_OF]-#gt;(Academy)<br/><i>année d'entrée ≤ saison de l'engagement</i>"]
  E1 --> E2
  E3["<b>3. Écurie-saison</b><br/>regroupement par écurie et saison<br/><i>au moins 2 académies DIFFÉRENTES</i>"]
  E2 --> E3
  E4["<b>4. Résultat</b><br/>une ligne par écurie-saison<br/><i>tri par nombre d'académies, puis saison décroissante ; LIMIT 25</i>"]
  E3 --> E4
```

## Q13 — Which teams are connected by multiple independent paths, such as a coach, sponsor, executive, or former teammate?

Couverture : PARTIELLE. Deux types de chemins existent dans les données : le PILOTE passé par les deux écuries, et l'ACADÉMIE qui alimente l'une et a formé un pilote de l'autre. Pas de sponsors ni de dirigeants dans les sources. Chemins indépendants = intermédiaires distincts ; types = nature des chemins.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Chemins par pilote | `(k1)<-[:DROVE_FOR]-(Driver)-[:DROVE_FOR]->(k2)` | k1 < k2 (chaque paire une fois) |
| 2. Chemins par académie | `(k1)<-[:FEEDS]-(Academy)<-[:MEMBER_OF]-(Driver)-[:DROVE_FOR]->(k2)` | k1 ≠ k2 ; paire remise en ordre k1 < k2 |
| 3. Regroupement | `par paire d'écuries` | intermédiaires distincts par type |
| 4. Résultat | `une ligne par paire` | total ≥ $chemins_min ; tri par nombre de types, puis total ; LIMIT 20 |

```mermaid
flowchart TD
  E1["<b>1. Chemins par pilote</b><br/>(k1)#lt;-[:DROVE_FOR]-(Driver)-[:DROVE_FOR]-#gt;(k2)<br/><i>k1 #lt; k2 (chaque paire une fois)</i>"]
  E2["<b>2. Chemins par académie</b><br/>(k1)#lt;-[:FEEDS]-(Academy)#lt;-[:MEMBER_OF]-(Driver)-[:DROVE_FOR]-#gt;(k2)<br/><i>k1 ≠ k2 ; paire remise en ordre k1 #lt; k2</i>"]
  E1 --> E2
  E3["<b>3. Regroupement</b><br/>par paire d'écuries<br/><i>intermédiaires distincts par type</i>"]
  E2 --> E3
  E4["<b>4. Résultat</b><br/>une ligne par paire<br/><i>total ≥ $chemins_min ; tri par nombre de types, puis total ; LIMIT 20</i>"]
  E3 --> E4
```

## Q14 — What documented links connect federation decision-makers, the executives of the teams involved, and their sponsors, either directly or through no more than three intermediaries?

Couverture : NON COUVERTE. Ni décideurs de la fédération (président de la FIA, directeur de course, commissaires), ni dirigeants d'écurie, ni sponsors dans des sources publiques structurées. Pistes : documents officiels de la FIA (décisions des commissaires, nominatifs), article Wikipédia « Formula One sponsorship liveries » (sponsors par écurie et par saison, tableaux hétérogènes).

## Q15 — Do the champions of the past ten years belong to shared training and coaching networks, even if they never directly shared an organization?

Couverture : complète, par substitution. Réseau de formation = académies (MEMBER_OF) ; réseau d'encadrement = coéquipiers (TEAMMATE_OF). Pour chaque paire de champions : académies de chacun, académie commune, organisation commune (écurie ou académie), et plus courte chaîne dans le réseau mêlant les deux.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Champions | `(Driver)-[:RANKED_IN]->(Season)` | position = 1 ; année < année courante ; année ≥ année courante − $saisons |
| 2. Paires | `champions × champions` | a.driverId < b.driverId |
| 3. Académies | `(Driver)-[:MEMBER_OF]->(Academy)` | pour chacun des deux |
| 4. Organisation commune | `EXISTS écurie commune OU académie commune` | à n'importe quelle époque |
| 5. Réseau commun | `shortestPath((a)-[:TEAMMATE_OF¦MEMBER_OF*..10]-(b))` | chemin non orienté, au plus 10 relations, passant par des pilotes ou des académies |

```mermaid
flowchart TD
  E1["<b>1. Champions</b><br/>(Driver)-[:RANKED_IN]-#gt;(Season)<br/><i>position = 1 ; année #lt; année courante ; année ≥ année courante − $saisons</i>"]
  E2["<b>2. Paires</b><br/>champions × champions<br/><i>a.driverId #lt; b.driverId</i>"]
  E1 --> E2
  E3["<b>3. Académies</b><br/>(Driver)-[:MEMBER_OF]-#gt;(Academy)<br/><i>pour chacun des deux</i>"]
  E2 --> E3
  E4["<b>4. Organisation commune</b><br/>EXISTS écurie commune OU académie commune<br/><i>à n'importe quelle époque</i>"]
  E3 --> E4
  E5["<b>5. Réseau commun</b><br/>shortestPath((a)-[:TEAMMATE_OF#124;MEMBER_OF*..10]-(b))<br/><i>chemin non orienté, au plus 10 relations, passant par des pilotes ou des académies</i>"]
  E4 --> E5
```

## Q16 — Do the two opponents have a shared history, such as a team, coach, training center, or mutual teammates? What indirect connections link them?

Couverture : complète, par substitution. Écuries communes, saisons comme coéquipiers (encadrement partagé), académies communes (centre de formation), coéquipiers communs, et plus courte chaîne dans le réseau des coéquipiers et des académies.

| Étape | Parcourt | Filtres |
|---|---|---|
| 1. Rivaux | `(prérequête) (Driver)-[:RANKED_IN]->(Season)` | dernière saison classée ; positions 1 et 2 |
| 2. Coéquipiers | `(a)-[:TEAMMATE_OF]-(b)` | saisons partagées |
| 3. Écuries communes | `(a)-[:DROVE_FOR]->(Constructor)<-[:DROVE_FOR]-(b)` | à n'importe quelle saison |
| 4. Académies communes | `(a)-[:MEMBER_OF]->(Academy)<-[:MEMBER_OF]-(b)` | avec les années de chacun |
| 5. Coéquipiers communs | `(a)-[:TEAMMATE_OF]-(Driver)-[:TEAMMATE_OF]-(b)` | intermédiaire distinct des deux |
| 6. Chaîne indirecte | `shortestPath((a)-[:TEAMMATE_OF¦MEMBER_OF*..10]-(b))` | non orientée, au plus 10 relations |

```mermaid
flowchart TD
  E1["<b>1. Rivaux</b><br/>(prérequête) (Driver)-[:RANKED_IN]-#gt;(Season)<br/><i>dernière saison classée ; positions 1 et 2</i>"]
  E2["<b>2. Coéquipiers</b><br/>(a)-[:TEAMMATE_OF]-(b)<br/><i>saisons partagées</i>"]
  E1 --> E2
  E3["<b>3. Écuries communes</b><br/>(a)-[:DROVE_FOR]-#gt;(Constructor)#lt;-[:DROVE_FOR]-(b)<br/><i>à n'importe quelle saison</i>"]
  E2 --> E3
  E4["<b>4. Académies communes</b><br/>(a)-[:MEMBER_OF]-#gt;(Academy)#lt;-[:MEMBER_OF]-(b)<br/><i>avec les années de chacun</i>"]
  E3 --> E4
  E5["<b>5. Coéquipiers communs</b><br/>(a)-[:TEAMMATE_OF]-(Driver)-[:TEAMMATE_OF]-(b)<br/><i>intermédiaire distinct des deux</i>"]
  E4 --> E5
  E6["<b>6. Chaîne indirecte</b><br/>shortestPath((a)-[:TEAMMATE_OF#124;MEMBER_OF*..10]-(b))<br/><i>non orientée, au plus 10 relations</i>"]
  E5 --> E6
```

