# Sauvegarde planifiée de la base : neo4j-admin database dump, rotation sur N jours.
# Base : client Docker officiel (Alpine), épinglé par empreinte. Le service pilote,
# par le socket Docker, l'arrêt et la relance du conteneur Neo4j : en édition
# Community, un dump exige une base arrêtée.
FROM docker:29-cli@sha256:6fae2214c3121a28d5aa639d09032f61310b7c9c75ffbad1025f261a1b621800

ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA256=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1

# Mise à jour et outils (diagnostic réseau, fuseaux, find/date GNU), en une couche.
RUN apk upgrade --no-cache \
 && apk add --no-cache iproute2 net-tools iputils bind-tools curl tzdata findutils coreutils \
 && curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
 && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
 && chmod 0755 /usr/local/bin/supercronic

COPY docker/sauvegarde/demarrer.sh docker/sauvegarde/sauvegarder.sh \
     docker/sauvegarde/restaurer.sh docker/sauvegarde/sante.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/demarrer.sh /usr/local/bin/sauvegarder.sh \
               /usr/local/bin/restaurer.sh /usr/local/bin/sante.sh

# Échouer à la construction si un prérequis manque.
RUN for outil in ss netstat ip ifconfig ping dig nslookup curl traceroute docker supercronic find sha256sum; do \
      command -v "$outil" >/dev/null || { echo "construction : outil manquant : $outil" >&2; exit 1; }; \
    done \
 && for s in demarrer sauvegarder restaurer sante; do sh -n "/usr/local/bin/$s.sh" \
      || { echo "construction : erreur de syntaxe dans $s.sh" >&2; exit 1; }; done \
 && printf '45 3 * * * true\n' > /tmp/essai && supercronic -no-reap -test /tmp/essai && rm /tmp/essai

ENTRYPOINT ["/usr/local/bin/demarrer.sh"]
