// =============================================================================
//  Graphe F1 — contraintes d'existence et de type (Neo4j ENTERPRISE, >= 5.9)
// =============================================================================
//
//  Neo4j Community ne connaît que l'unicité : les contraintes ci-dessous y sont
//  refusées. charger.py n'applique ce fichier que si dbms.components() annonce
//  l'édition enterprise, et le dit dans les deux cas. Sur Community, la même
//  garantie est vérifiée APRÈS chargement par charger.py (contrôles d'invariants).
//
//  Pas de NODE KEY ici : une clé de nœud sur une propriété déjà couverte par une
//  contrainte d'unicité serait refusée (index équivalent existant). Unicité
//  (fichier 01) + existence (ce fichier) équivalent à une clé de nœud.
//
//  Les types déclarés sont exactement ceux qu'écrit charger.py. Une propriété
//  facultative (absente pour les saisons anciennes) n'a qu'une contrainte de
//  type : une contrainte de type tolère l'absence, pas une valeur d'un autre type.
// -----------------------------------------------------------------------------

// --- Season ------------------------------------------------------------------
CREATE CONSTRAINT season_year_exists IF NOT EXISTS FOR (s:Season) REQUIRE s.year IS NOT NULL;
CREATE CONSTRAINT season_year_type   IF NOT EXISTS FOR (s:Season) REQUIRE s.year IS :: INTEGER;
CREATE CONSTRAINT season_url_type    IF NOT EXISTS FOR (s:Season) REQUIRE s.url IS :: STRING;

// --- Circuit -----------------------------------------------------------------
CREATE CONSTRAINT circuit_id_exists     IF NOT EXISTS FOR (c:Circuit) REQUIRE c.circuitId IS NOT NULL;
CREATE CONSTRAINT circuit_id_type       IF NOT EXISTS FOR (c:Circuit) REQUIRE c.circuitId IS :: STRING;
CREATE CONSTRAINT circuit_name_exists   IF NOT EXISTS FOR (c:Circuit) REQUIRE c.name IS NOT NULL;
CREATE CONSTRAINT circuit_name_type     IF NOT EXISTS FOR (c:Circuit) REQUIRE c.name IS :: STRING;
CREATE CONSTRAINT circuit_locality_type IF NOT EXISTS FOR (c:Circuit) REQUIRE c.locality IS :: STRING;
CREATE CONSTRAINT circuit_lat_type      IF NOT EXISTS FOR (c:Circuit) REQUIRE c.latitude IS :: FLOAT;
CREATE CONSTRAINT circuit_lng_type      IF NOT EXISTS FOR (c:Circuit) REQUIRE c.longitude IS :: FLOAT;
CREATE CONSTRAINT circuit_location_type IF NOT EXISTS FOR (c:Circuit) REQUIRE c.location IS :: POINT;

// --- Country / Nationality / Status -----------------------------------------
CREATE CONSTRAINT country_name_exists     IF NOT EXISTS FOR (p:Country)     REQUIRE p.name IS NOT NULL;
CREATE CONSTRAINT country_name_type       IF NOT EXISTS FOR (p:Country)     REQUIRE p.name IS :: STRING;
CREATE CONSTRAINT nationality_name_exists IF NOT EXISTS FOR (n:Nationality) REQUIRE n.name IS NOT NULL;
CREATE CONSTRAINT nationality_name_type   IF NOT EXISTS FOR (n:Nationality) REQUIRE n.name IS :: STRING;
CREATE CONSTRAINT status_name_exists      IF NOT EXISTS FOR (s:Status)      REQUIRE s.name IS NOT NULL;
CREATE CONSTRAINT status_name_type        IF NOT EXISTS FOR (s:Status)      REQUIRE s.name IS :: STRING;

// --- Driver ------------------------------------------------------------------
CREATE CONSTRAINT driver_id_exists          IF NOT EXISTS FOR (d:Driver) REQUIRE d.driverId IS NOT NULL;
CREATE CONSTRAINT driver_id_type            IF NOT EXISTS FOR (d:Driver) REQUIRE d.driverId IS :: STRING;
CREATE CONSTRAINT driver_family_name_exists IF NOT EXISTS FOR (d:Driver) REQUIRE d.familyName IS NOT NULL;
CREATE CONSTRAINT driver_family_name_type   IF NOT EXISTS FOR (d:Driver) REQUIRE d.familyName IS :: STRING;
CREATE CONSTRAINT driver_given_name_type    IF NOT EXISTS FOR (d:Driver) REQUIRE d.givenName IS :: STRING;
CREATE CONSTRAINT driver_full_name_type     IF NOT EXISTS FOR (d:Driver) REQUIRE d.fullName IS :: STRING;
CREATE CONSTRAINT driver_code_type          IF NOT EXISTS FOR (d:Driver) REQUIRE d.code IS :: STRING;
CREATE CONSTRAINT driver_number_type        IF NOT EXISTS FOR (d:Driver) REQUIRE d.permanentNumber IS :: INTEGER;
CREATE CONSTRAINT driver_birth_type         IF NOT EXISTS FOR (d:Driver) REQUIRE d.dateOfBirth IS :: DATE;

// --- Constructor -------------------------------------------------------------
CREATE CONSTRAINT constructor_id_exists   IF NOT EXISTS FOR (k:Constructor) REQUIRE k.constructorId IS NOT NULL;
CREATE CONSTRAINT constructor_id_type     IF NOT EXISTS FOR (k:Constructor) REQUIRE k.constructorId IS :: STRING;
CREATE CONSTRAINT constructor_name_exists IF NOT EXISTS FOR (k:Constructor) REQUIRE k.name IS NOT NULL;
CREATE CONSTRAINT constructor_name_type   IF NOT EXISTS FOR (k:Constructor) REQUIRE k.name IS :: STRING;

// --- Race --------------------------------------------------------------------
CREATE CONSTRAINT race_id_exists     IF NOT EXISTS FOR (r:Race) REQUIRE r.raceId IS NOT NULL;
CREATE CONSTRAINT race_id_type       IF NOT EXISTS FOR (r:Race) REQUIRE r.raceId IS :: STRING;
CREATE CONSTRAINT race_season_exists IF NOT EXISTS FOR (r:Race) REQUIRE r.season IS NOT NULL;
CREATE CONSTRAINT race_season_type   IF NOT EXISTS FOR (r:Race) REQUIRE r.season IS :: INTEGER;
CREATE CONSTRAINT race_round_exists  IF NOT EXISTS FOR (r:Race) REQUIRE r.round IS NOT NULL;
CREATE CONSTRAINT race_round_type    IF NOT EXISTS FOR (r:Race) REQUIRE r.round IS :: INTEGER;
CREATE CONSTRAINT race_name_exists   IF NOT EXISTS FOR (r:Race) REQUIRE r.name IS NOT NULL;
CREATE CONSTRAINT race_date_exists   IF NOT EXISTS FOR (r:Race) REQUIRE r.date IS NOT NULL;
CREATE CONSTRAINT race_date_type     IF NOT EXISTS FOR (r:Race) REQUIRE r.date IS :: DATE;
CREATE CONSTRAINT race_starts_type   IF NOT EXISTS FOR (r:Race) REQUIRE r.startsAt IS :: ZONED DATETIME;

// --- RaceResult / SprintResult ----------------------------------------------
CREATE CONSTRAINT race_result_id_exists     IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.resultId IS NOT NULL;
CREATE CONSTRAINT race_result_id_type       IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.resultId IS :: STRING;
CREATE CONSTRAINT race_result_ptext_exists  IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.positionText IS NOT NULL;
CREATE CONSTRAINT race_result_points_exists IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.points IS NOT NULL;
CREATE CONSTRAINT race_result_points_type   IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.points IS :: FLOAT;
CREATE CONSTRAINT race_result_position_type IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.position IS :: INTEGER;
CREATE CONSTRAINT race_result_grid_type     IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.grid IS :: INTEGER;
CREATE CONSTRAINT race_result_laps_type     IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.laps IS :: INTEGER;
CREATE CONSTRAINT race_result_millis_type   IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.timeMillis IS :: INTEGER;
CREATE CONSTRAINT race_result_fl_ms_type    IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.fastestLapMillis IS :: INTEGER;
CREATE CONSTRAINT race_result_fl_kph_type   IF NOT EXISTS FOR (r:RaceResult) REQUIRE r.fastestLapAvgSpeedKph IS :: FLOAT;

CREATE CONSTRAINT sprint_result_id_exists     IF NOT EXISTS FOR (r:SprintResult) REQUIRE r.resultId IS NOT NULL;
CREATE CONSTRAINT sprint_result_id_type       IF NOT EXISTS FOR (r:SprintResult) REQUIRE r.resultId IS :: STRING;
CREATE CONSTRAINT sprint_result_ptext_exists  IF NOT EXISTS FOR (r:SprintResult) REQUIRE r.positionText IS NOT NULL;
CREATE CONSTRAINT sprint_result_points_exists IF NOT EXISTS FOR (r:SprintResult) REQUIRE r.points IS NOT NULL;
CREATE CONSTRAINT sprint_result_points_type   IF NOT EXISTS FOR (r:SprintResult) REQUIRE r.points IS :: FLOAT;
CREATE CONSTRAINT sprint_result_position_type IF NOT EXISTS FOR (r:SprintResult) REQUIRE r.position IS :: INTEGER;
CREATE CONSTRAINT sprint_result_millis_type   IF NOT EXISTS FOR (r:SprintResult) REQUIRE r.timeMillis IS :: INTEGER;

// --- QualifyingResult --------------------------------------------------------
CREATE CONSTRAINT qualifying_id_exists     IF NOT EXISTS FOR (q:QualifyingResult) REQUIRE q.resultId IS NOT NULL;
CREATE CONSTRAINT qualifying_id_type       IF NOT EXISTS FOR (q:QualifyingResult) REQUIRE q.resultId IS :: STRING;
CREATE CONSTRAINT qualifying_position_type IF NOT EXISTS FOR (q:QualifyingResult) REQUIRE q.position IS :: INTEGER;
CREATE CONSTRAINT qualifying_q1_ms_type    IF NOT EXISTS FOR (q:QualifyingResult) REQUIRE q.q1Millis IS :: INTEGER;
CREATE CONSTRAINT qualifying_q2_ms_type    IF NOT EXISTS FOR (q:QualifyingResult) REQUIRE q.q2Millis IS :: INTEGER;
CREATE CONSTRAINT qualifying_q3_ms_type    IF NOT EXISTS FOR (q:QualifyingResult) REQUIRE q.q3Millis IS :: INTEGER;

// --- PitStop / LapTime -------------------------------------------------------
CREATE CONSTRAINT pit_stop_id_exists   IF NOT EXISTS FOR (p:PitStop) REQUIRE p.pitStopId IS NOT NULL;
CREATE CONSTRAINT pit_stop_id_type     IF NOT EXISTS FOR (p:PitStop) REQUIRE p.pitStopId IS :: STRING;
CREATE CONSTRAINT pit_stop_stop_exists IF NOT EXISTS FOR (p:PitStop) REQUIRE p.stop IS NOT NULL;
CREATE CONSTRAINT pit_stop_stop_type   IF NOT EXISTS FOR (p:PitStop) REQUIRE p.stop IS :: INTEGER;
CREATE CONSTRAINT pit_stop_lap_exists  IF NOT EXISTS FOR (p:PitStop) REQUIRE p.lap IS NOT NULL;
CREATE CONSTRAINT pit_stop_lap_type    IF NOT EXISTS FOR (p:PitStop) REQUIRE p.lap IS :: INTEGER;
CREATE CONSTRAINT pit_stop_tod_type    IF NOT EXISTS FOR (p:PitStop) REQUIRE p.timeOfDay IS :: LOCAL TIME;
CREATE CONSTRAINT pit_stop_ms_type     IF NOT EXISTS FOR (p:PitStop) REQUIRE p.durationMillis IS :: INTEGER;

CREATE CONSTRAINT lap_time_id_exists  IF NOT EXISTS FOR (t:LapTime) REQUIRE t.lapTimeId IS NOT NULL;
CREATE CONSTRAINT lap_time_id_type    IF NOT EXISTS FOR (t:LapTime) REQUIRE t.lapTimeId IS :: STRING;
CREATE CONSTRAINT lap_time_lap_exists IF NOT EXISTS FOR (t:LapTime) REQUIRE t.lap IS NOT NULL;
CREATE CONSTRAINT lap_time_lap_type   IF NOT EXISTS FOR (t:LapTime) REQUIRE t.lap IS :: INTEGER;
CREATE CONSTRAINT lap_time_pos_type   IF NOT EXISTS FOR (t:LapTime) REQUIRE t.position IS :: INTEGER;
CREATE CONSTRAINT lap_time_ms_type    IF NOT EXISTS FOR (t:LapTime) REQUIRE t.millis IS :: INTEGER;

// --- Relations ---------------------------------------------------------------
CREATE CONSTRAINT drove_for_key_exists    IF NOT EXISTS FOR ()-[r:DROVE_FOR]-() REQUIRE r.key IS NOT NULL;
CREATE CONSTRAINT drove_for_season_exists IF NOT EXISTS FOR ()-[r:DROVE_FOR]-() REQUIRE r.season IS NOT NULL;
CREATE CONSTRAINT drove_for_season_type   IF NOT EXISTS FOR ()-[r:DROVE_FOR]-() REQUIRE r.season IS :: INTEGER;

CREATE CONSTRAINT ranked_in_key_exists    IF NOT EXISTS FOR ()-[r:RANKED_IN]-() REQUIRE r.key IS NOT NULL;
CREATE CONSTRAINT ranked_in_points_exists IF NOT EXISTS FOR ()-[r:RANKED_IN]-() REQUIRE r.points IS NOT NULL;
CREATE CONSTRAINT ranked_in_points_type   IF NOT EXISTS FOR ()-[r:RANKED_IN]-() REQUIRE r.points IS :: FLOAT;
CREATE CONSTRAINT ranked_in_position_type IF NOT EXISTS FOR ()-[r:RANKED_IN]-() REQUIRE r.position IS :: INTEGER;
CREATE CONSTRAINT ranked_in_wins_type     IF NOT EXISTS FOR ()-[r:RANKED_IN]-() REQUIRE r.wins IS :: INTEGER;
CREATE CONSTRAINT ranked_in_round_type    IF NOT EXISTS FOR ()-[r:RANKED_IN]-() REQUIRE r.afterRound IS :: INTEGER;
