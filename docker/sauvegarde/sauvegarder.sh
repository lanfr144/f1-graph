#!/bin/sh
# Sauvegarde de la base Neo4j par neo4j-admin database dump, puis rotation.
#
# Neo4j Community ne sait pas arrêter une seule base : le dump exige d'arrêter le
# conteneur. Étapes, toutes journalisées :
#   1. attendre qu'aucun chargement ne soit en cours (etat.json du chargeur) ;
#   2. arrêter Neo4j proprement ; 3. dump dans un conteneur jetable de la même image ;
#   4. relancer Neo4j (TOUJOURS, même en cas d'échec : trap) et attendre qu'il soit sain ;
#   5. nommer, empreinter, puis supprimer les dumps de plus de SAUVEGARDE_JOURS jours.
# Une rotation n'a lieu qu'après un dump réussi : on ne supprime jamais la dernière
# bonne sauvegarde pour la remplacer par rien.
set -eu
set -o pipefail

journal() { echo "$(date '+%Y-%m-%d %H:%M:%S%z') [sauvegarde] $*"; }
echec()   { journal "ÉCHEC : $*"; exit 1; }

: "${F1_PROJET:?}" "${SAUVEGARDE_JOURS:?}" "${SAUVEGARDE_ATTENTE_MAX_S:?}"
: "${HOTE_UID:?}" "${HOTE_GID:?}"

NEO=$(docker ps -aq --filter "label=com.docker.compose.project=${F1_PROJET}" \
                    --filter "label=com.docker.compose.service=neo4j" | head -1)
[ -n "${NEO}" ] || echec "conteneur neo4j du projet ${F1_PROJET} introuvable"
IMAGE=$(docker inspect --format '{{.Config.Image}}' "${NEO}")
MOI=$(hostname)
HOTE_SAUVEGARDES=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/sauvegardes"}}{{.Source}}{{end}}{{end}}' "${MOI}")
[ -n "${HOTE_SAUVEGARDES}" ] || echec "montage /sauvegardes introuvable sur ce conteneur"

# 1. Pas pendant un chargement : il échouerait, base arrêtée.
attendu=0
while [ -f /donnees/etat.json ] && grep -q '"statut": "en_cours"' /donnees/etat.json \
      && head -c 400 /donnees/etat.json | grep -q '"execution"'; do
  age=$(( $(date +%s) - $(stat -c %Y /donnees/etat.json) ))
  [ "${age}" -gt 7200 ] && { journal "état « en_cours » inactif depuis ${age} s : chargement interrompu, on continue"; break; }
  [ "${attendu}" -ge "${SAUVEGARDE_ATTENTE_MAX_S}" ] && echec "un chargement est en cours depuis plus de ${attendu} s : sauvegarde reportée au prochain créneau"
  journal "chargement en cours : attente (${attendu} s)"
  sleep 60; attendu=$((attendu + 60))
done

debut=$(date +%s)
horodatage=$(date +%Y%m%d-%H%M%S)
travail="/sauvegardes/.en-cours-${horodatage}"
mkdir -p "${travail}"

relancer() {
  if [ "$(docker inspect --format '{{.State.Running}}' "${NEO}")" != "true" ]; then
    journal "relance de Neo4j"
    docker start "${NEO}" >/dev/null
  fi
}
# En cas d'échec à n'importe quelle étape : Neo4j relancé, répertoire de travail nettoyé.
trap 'relancer; rm -rf "${travail}"' EXIT

# 2. Arrêt propre (le délai laisse Neo4j fermer sa base).
journal "arrêt de Neo4j (${NEO}) pour le dump"
docker stop -t 120 "${NEO}" >/dev/null

# 3. Dump, par la même image que la base, avec ses volumes de données.
journal "dump : neo4j-admin database dump neo4j (image ${IMAGE})"
docker run --rm --user "${HOTE_UID}:${HOTE_GID}" --volumes-from "${NEO}" \
  -v "${HOTE_SAUVEGARDES}:/sauvegardes" --entrypoint /var/lib/neo4j/bin/neo4j-admin "${IMAGE}" \
  database dump neo4j --to-path="${travail}" --overwrite-destination=true 2>&1 \
  | grep -v '^Files: ' \
  || echec "neo4j-admin database dump a échoué (Neo4j va être relancé)"

# 4. Relance, et attente de la santé (le trap reste armé : il nettoiera en fin de script).
relancer
for i in $(seq 1 40); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' "${NEO}")" = "healthy" ] && break
  sleep 5
done
[ "$(docker inspect --format '{{.State.Health.Status}}' "${NEO}")" = "healthy" ] \
  || journal "ATTENTION : Neo4j relancé mais pas encore sain après 200 s"
journal "Neo4j relancé et sain, interruption de $(( $(date +%s) - debut )) s"

# 5. Nommage, empreinte, rotation.
fichier="/sauvegardes/neo4j-${horodatage}.dump"
[ -s "${travail}/neo4j.dump" ] || echec "dump vide ou absent"
mv "${travail}/neo4j.dump" "${fichier}"
rm -rf "${travail}"
( cd /sauvegardes && sha256sum "$(basename "${fichier}")" > "$(basename "${fichier}").sha256" )
journal "sauvegarde écrite : $(basename "${fichier}") ($(du -h "${fichier}" | cut -f1))"

supprimes=$(find /sauvegardes -maxdepth 1 -name 'neo4j-*.dump' -mtime +$((SAUVEGARDE_JOURS - 1)) -print)
for f in ${supprimes}; do
  rm -f "${f}" "${f}.sha256"
  journal "rotation : $(basename "${f}") supprimée (plus de ${SAUVEGARDE_JOURS} jours)"
done
journal "sauvegardes conservées : $(find /sauvegardes -maxdepth 1 -name 'neo4j-*.dump' | sort | xargs -n1 basename | tr '\n' ' ')"
