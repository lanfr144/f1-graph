#!/bin/sh
# Healthcheck de la sauvegarde : ce que le service rend, c'est une sauvegarde récente.
# Sain si le socket Docker répond ET (la dernière sauvegarde a moins de
# SAUVEGARDE_AGE_MAX_S secondes, OU le service a démarré depuis moins que ce délai et
# n'a pas encore atteint son premier créneau).
set -eu
: "${SAUVEGARDE_AGE_MAX_S:?}"

docker info >/dev/null 2>&1 || { echo "MALADE : socket Docker injoignable"; exit 1; }
maintenant=$(date +%s)
derniere=$(find /sauvegardes -maxdepth 1 -name 'neo4j-*.dump' -printf '%T@ %f\n' 2>/dev/null | sort -n | tail -1)
if [ -n "${derniere}" ]; then
  age=$(( maintenant - ${derniere%%.*} ))
  if [ "${age}" -le "${SAUVEGARDE_AGE_MAX_S}" ]; then
    echo "SAIN : dernière sauvegarde ${derniere#* } il y a ${age} s"; exit 0
  fi
  echo "MALADE : dernière sauvegarde ${derniere#* } il y a ${age} s (> ${SAUVEGARDE_AGE_MAX_S})"; exit 1
fi
demarre=$(cat /tmp/demarre 2>/dev/null || echo 0)
if [ $(( maintenant - demarre )) -le "${SAUVEGARDE_AGE_MAX_S}" ]; then
  echo "SAIN : aucune sauvegarde encore, premier créneau à venir"; exit 0
fi
echo "MALADE : aucune sauvegarde depuis le démarrage du service"; exit 1
