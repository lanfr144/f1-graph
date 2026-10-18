#!/bin/sh
# Point d'entrée de la sauvegarde : vérifie la configuration, puis planifie
# sauvegarder.sh selon SAUVEGARDE_CRON. Journal sur la sortie standard.
set -eu

: "${SAUVEGARDE_CRON:?SAUVEGARDE_CRON manquant (ex. '45 3 * * *')}"
: "${SAUVEGARDE_JOURS:?SAUVEGARDE_JOURS manquant (ex. 7)}"
: "${F1_PROJET:?F1_PROJET manquant (nom du projet compose)}"

journal() { echo "$(date '+%Y-%m-%d %H:%M:%S%z') [sauvegarde] $*"; }

docker info >/dev/null 2>&1 || { journal "ÉCHEC : socket Docker injoignable (DOCKER_GID ?)"; exit 1; }
[ -w /sauvegardes ] || { journal "ÉCHEC : /sauvegardes non inscriptible par $(id -u):$(id -g)"; exit 1; }
date +%s > /tmp/demarre

printf '%s /usr/local/bin/sauvegarder.sh\n' "${SAUVEGARDE_CRON}" > /tmp/sauvegarde.crontab
supercronic -no-reap -test /tmp/sauvegarde.crontab
journal "planification : ${SAUVEGARDE_CRON} (fuseau ${TZ:-UTC}), conservation ${SAUVEGARDE_JOURS} jours, dans /sauvegardes"
journal "sauvegardes présentes : $(find /sauvegardes -maxdepth 1 -name 'neo4j-*.dump' | wc -l)"
exec supercronic -no-reap -passthrough-logs /tmp/sauvegarde.crontab
