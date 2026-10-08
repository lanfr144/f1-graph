// =============================================================================
//  Graphe F1 — index (Neo4j >= 5.7)
// =============================================================================
//
//  Les clés (driverId, raceId, resultId…) sont déjà indexées par leurs
//  contraintes d'unicité (01_contraintes.cypher). Les index de recherche par
//  étiquette et par type de relation (LOOKUP) existent par défaut : ne pas les
//  supprimer, MATCH (n:Label) en dépend.
//
//  Chaque index ci-dessous sert une requête de 04_requetes.cypher, citée en
//  regard. Un index qu'aucune requête n'utilise ralentit les écritures pour rien.
// -----------------------------------------------------------------------------

// Courses dans un intervalle de dates (requête R1).
CREATE RANGE INDEX race_date IF NOT EXISTS
FOR (r:Race) ON (r.date);

// Courses d'une saison, sans passer par le nœud Season (requête R2). L'index
// composite (season, round) de la contrainte d'unicité ne sert qu'aux requêtes
// qui filtrent les deux propriétés : on ne compte pas dessus pour la saison seule.
CREATE RANGE INDEX race_season IF NOT EXISTS
FOR (r:Race) ON (r.season);

// Vainqueurs, podiums : filtre sur la position d'arrivée (requête R3).
CREATE RANGE INDEX race_result_position IF NOT EXISTS
FOR (r:RaceResult) ON (r.position);

// Champions du monde : filtre sur la position au classement final (requête R4).
CREATE RANGE INDEX ranked_in_position IF NOT EXISTS
FOR ()-[k:RANKED_IN]-() ON (k.position);

// Arrêts les plus rapides : tri sur la durée, servi par l'index (requête R5).
CREATE RANGE INDEX pit_stop_duration IF NOT EXISTS
FOR (p:PitStop) ON (p.durationMillis);

// Circuits dans un rayon donné (requête R6) : point.distance() et
// point.withinBBox() ne sont servis que par un index POINT.
CREATE POINT INDEX circuit_location IF NOT EXISTS
FOR (c:Circuit) ON (c.location);

// Recherche de pilote par nom, tolérante aux accents et à la casse (requête R7) :
// « raikkonen » trouve « Räikkönen », « perez » trouve « Pérez ». Un index RANGE
// sur familyName ne servirait ni l'un ni l'autre, ni la recherche infixe.
CREATE FULLTEXT INDEX driver_name_search IF NOT EXISTS
FOR (d:Driver) ON EACH [d.givenName, d.familyName]
OPTIONS { indexConfig: { `fulltext.analyzer`: 'standard-folding' } };

// Recherche d'écurie par nom (requête R8).
CREATE FULLTEXT INDEX constructor_name_search IF NOT EXISTS
FOR (k:Constructor) ON EACH [k.name]
OPTIONS { indexConfig: { `fulltext.analyzer`: 'standard-folding' } };

// Recherche de circuit par nom ou par localité (requête R9).
CREATE FULLTEXT INDEX circuit_name_search IF NOT EXISTS
FOR (c:Circuit) ON EACH [c.name, c.locality]
OPTIONS { indexConfig: { `fulltext.analyzer`: 'standard-folding' } };
