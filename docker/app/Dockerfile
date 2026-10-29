# Image applicative unique, utilisée par trois services :
#   chargeur  chargement initial (repris s'il est interrompu), puis deltas planifiés ;
#   web       interface Streamlit (questions, graphes interactifs, santé) ;
#   tests     tests d'intégration contre la base (profil « tests »).
FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

# Identifiants de l'utilisateur hôte : les fichiers écrits dans le volume monté
# (cache, journaux, état) lui appartiennent et restent lisibles sur l'hôte.
ARG HOTE_UID
ARG HOTE_GID
# supercronic : cron conçu pour les conteneurs (sans root, journal sur stdout).
# Version et empreinte relevées sur https://github.com/aptible/supercronic/releases
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA256=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1

RUN test -n "$HOTE_UID" && test -n "$HOTE_GID" \
      || { echo "construction : HOTE_UID et HOTE_GID sont requis (voir .env.docker.example)" >&2; exit 1; }

# Mise à jour, outils de diagnostic réseau, fuseaux horaires, en une seule couche.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get check \
 && apt-get install -y --no-install-recommends \
      ca-certificates tzdata iproute2 net-tools iputils-ping dnsutils curl traceroute \
 && apt-get autoremove -y \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
 && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
 && chmod 0755 /usr/local/bin/supercronic

WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

COPY *.py ./
COPY schema/ schema/
COPY requetes/ requetes/
COPY referentiel/ referentiel/
COPY app/ app/
COPY tests/ tests/
COPY .streamlit/ .streamlit/
COPY docs/modele-graphe.md docs/modele-graphe.md
COPY docker/app/demarrer.sh /usr/local/bin/demarrer.sh

RUN groupadd -o -g "$HOTE_GID" f1 \
 && useradd -o -u "$HOTE_UID" -g "$HOTE_GID" -M -d /tmp -s /usr/sbin/nologin f1 \
 && chmod 0755 /usr/local/bin/demarrer.sh

# Échouer à la construction si un prérequis manque : outils, modules, scripts, cron,
# et tests unitaires (sans réseau ni base).
RUN for outil in ss netstat ip ifconfig ping dig nslookup curl traceroute supercronic; do \
      command -v "$outil" >/dev/null || { echo "construction : outil manquant : $outil" >&2; exit 1; }; \
    done \
 && python -c "import neo4j, streamlit, pyvis" \
      || { echo "construction : module Python manquant (neo4j, streamlit ou pyvis)" >&2; exit 1; } \
 && python -m compileall -q /app \
 && python -c "import commun, extraire, transformer, charger, pipeline, manifeste, verifier, questions, sante, referentiel, complements" \
      || { echo "construction : un module du projet ne s'importe pas" >&2; exit 1; } \
 && python -m unittest -q tests.test_unitaires \
      || { echo "construction : tests unitaires en échec" >&2; exit 1; } \
 && printf '*/5 * * * * true\n' > /tmp/essai.crontab && supercronic -test /tmp/essai.crontab \
      || { echo "construction : supercronic inutilisable" >&2; exit 1; } \
 && rm -f /tmp/essai.crontab

USER f1
ENV PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    F1_DONNEES=/donnees
ENTRYPOINT ["/usr/local/bin/demarrer.sh"]
