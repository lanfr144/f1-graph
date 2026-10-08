// =============================================================================
//  Graphe F1 — contraintes d'unicité (Neo4j Community ou Enterprise, >= 5.7)
// =============================================================================
//
//  Chaque contrainte d'unicité crée son propre index RANGE : ne pas créer en
//  plus un index sur la même propriété, Neo4j le refuserait.
//
//  Toutes les instructions sont idempotentes (IF NOT EXISTS) : le fichier se
//  rejoue sans erreur.
//
//  Ne figurent ici que les étiquettes et les relations que charger.py alimente.
//  Rien n'est modélisé « pour plus tard » : un type vide induirait en erreur.
// -----------------------------------------------------------------------------

// --- Référentiels -----------------------------------------------------------

// Saison du championnat du monde, identifiée par son année.
CREATE CONSTRAINT season_year_unique IF NOT EXISTS
FOR (s:Season) REQUIRE s.year IS UNIQUE;

// Circuit, identifié par l'identifiant stable de l'API (ex. 'monza').
CREATE CONSTRAINT circuit_id_unique IF NOT EXISTS
FOR (c:Circuit) REQUIRE c.circuitId IS UNIQUE;

// Pays tel que l'API le nomme ('UK', 'USA', 'Italy'…) : aucune normalisation ISO
// n'est inventée, faute de table de correspondance publiée par la source.
CREATE CONSTRAINT country_name_unique IF NOT EXISTS
FOR (p:Country) REQUIRE p.name IS UNIQUE;

// Nationalité (gentilé : 'British', 'Dutch'…). Distincte de Country : l'API ne
// fournit aucun lien entre les deux, et le deviner serait inventer.
CREATE CONSTRAINT nationality_name_unique IF NOT EXISTS
FOR (n:Nationality) REQUIRE n.name IS UNIQUE;

// Pilote. Le trigramme 'code' n'est PAS unique (Michael et Mick Schumacher : MSC),
// le numéro permanent non plus (réattribué) : seul driverId fait foi.
CREATE CONSTRAINT driver_id_unique IF NOT EXISTS
FOR (d:Driver) REQUIRE d.driverId IS UNIQUE;

// Constructeur (écurie).
CREATE CONSTRAINT constructor_id_unique IF NOT EXISTS
FOR (k:Constructor) REQUIRE k.constructorId IS UNIQUE;

// Statut d'arrivée ('Finished', '+1 Lap', 'Engine'…), identifié par son libellé :
// c'est le libellé, et non un identifiant, que portent les résultats.
CREATE CONSTRAINT status_name_unique IF NOT EXISTS
FOR (s:Status) REQUIRE s.name IS UNIQUE;

// --- Grand Prix --------------------------------------------------------------

// Clé technique 'AAAA-RR' (ex. '2024-01').
CREATE CONSTRAINT race_id_unique IF NOT EXISTS
FOR (r:Race) REQUIRE r.raceId IS UNIQUE;

// Clé métier : une seule manche d'un numéro donné par saison.
CREATE CONSTRAINT race_season_round_unique IF NOT EXISTS
FOR (r:Race) REQUIRE (r.season, r.round) IS UNIQUE;

// --- Résultats (nœuds n-aires : pilote × constructeur × course) -------------
//
// Clé 'AAAA-RR-<numéro>-<driverId>'. Le numéro de voiture est indispensable :
// dans les années 1950, un même pilote peut courir deux voitures dans la même
// course, et deux pilotes peuvent partager une voiture (même position).

CREATE CONSTRAINT race_result_id_unique IF NOT EXISTS
FOR (r:RaceResult) REQUIRE r.resultId IS UNIQUE;

CREATE CONSTRAINT sprint_result_id_unique IF NOT EXISTS
FOR (r:SprintResult) REQUIRE r.resultId IS UNIQUE;

CREATE CONSTRAINT qualifying_result_id_unique IF NOT EXISTS
FOR (q:QualifyingResult) REQUIRE q.resultId IS UNIQUE;

// Arrêt au stand : 'AAAA-RR-<driverId>-<numéro d'arrêt>'.
CREATE CONSTRAINT pit_stop_id_unique IF NOT EXISTS
FOR (p:PitStop) REQUIRE p.pitStopId IS UNIQUE;

// Temps au tour : 'AAAA-RR-<driverId>-<tour>'. Chargé seulement si extrait.
CREATE CONSTRAINT lap_time_id_unique IF NOT EXISTS
FOR (t:LapTime) REQUIRE t.lapTimeId IS UNIQUE;

// --- Relations portant une clé (Neo4j >= 5.7) --------------------------------

// (Driver)-[:DROVE_FOR]->(Constructor), une par saison : 'AAAA:<driverId>:<constructorId>'.
CREATE CONSTRAINT drove_for_key_unique IF NOT EXISTS
FOR ()-[r:DROVE_FOR]-() REQUIRE r.key IS UNIQUE;

// (Driver|Constructor)-[:RANKED_IN]->(Season), classement final :
// 'driver:AAAA:<driverId>' ou 'constructor:AAAA:<constructorId>'.
CREATE CONSTRAINT ranked_in_key_unique IF NOT EXISTS
FOR ()-[r:RANKED_IN]-() REQUIRE r.key IS UNIQUE;
