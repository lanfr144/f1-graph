#!/bin/sh
# Restauration d'une sauvegarde : REMPLACE la base courante.
#
#   docker compose exec sauvegarde restaurer.sh                       # liste les sauvegardes
#   docker compose exec sauvegarde restaurer.sh neo4j-20261018-034500.dump --confirmer
#
# Vérifie l'empreinte, arrête Neo4j, charge le dump (neo4j-admin database load),
# relance Neo4j. Sans --confirmer, ne fait rien d'autre qu'annoncer ce qu'il ferait.
set -eu

journal() { echo "$(date '+%Y-%m-%d %H:%M:%S%z') [restauration] $*"; }
echec()   { journal "ÉCHEC : $*"; exit 1; }

: "${F1_PROJET:?}" "${HOTE_UID:?}" "${HOTE_GID:?}"

if [ $# -lt 1 ]; then
  echo "Sauvegardes disponibles :"
  find /sauvegardes -maxdepth 1 -name 'neo4j-*.dump' | sort | while read -r f; do
    echo "  $(basename "$f")  $(du -h "$f" | cut -f1)"
  done
  exit 0
fi

nom=$(basename "$1")
fichier="/sauvegardes/${nom}"
[ -f "${fichier}" ] || echec "${nom} introuvable dans /sauvegardes"
( cd /sauvegardes && sha256sum -c "${nom}.sha256" >/dev/null ) || echec "empreinte de ${nom} invalide : fichier altéré"
journal "empreinte de ${nom} vérifiée"

if [ "${2:-}" != "--confirmer" ]; then
  journal "la base courante serait REMPLACÉE par ${nom} ; ajouter --confirmer pour le faire"
  exit 0
fi

NEO=$(docker ps -aq --filter "label=com.docker.compose.project=${F1_PROJET}" \
                    --filter "label=com.docker.compose.service=neo4j" | head -1)
[ -n "${NEO}" ] || echec "conteneur neo4j du projet ${F1_PROJET} introuvable"
IMAGE=$(docker inspect --format '{{.Config.Image}}' "${NEO}")
HOTE_SAUVEGARDES=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/sauvegardes"}}{{.Source}}{{end}}{{end}}' "$(hostname)")
travail="/sauvegardes/.restauration"
rm -rf "${travail}" && mkdir -p "${travail}" && cp "${fichier}" "${travail}/neo4j.dump"

trap 'docker start "${NEO}" >/dev/null; rm -rf "${travail}"' EXIT
journal "arrêt de Neo4j"
docker stop -t 120 "${NEO}" >/dev/null
journal "chargement de ${nom}"
docker run --rm --user "${HOTE_UID}:${HOTE_GID}" --volumes-from "${NEO}" \
  -v "${HOTE_SAUVEGARDES}:/sauvegardes" --entrypoint /var/lib/neo4j/bin/neo4j-admin "${IMAGE}" \
  database load neo4j --from-path="${travail}" --overwrite-destination=true \
  || echec "neo4j-admin database load a échoué (Neo4j va être relancé sur la base précédente)"
journal "restauration terminée ; relance de Neo4j"
