FROM debian:trixie-slim

# Ungepufferte Python-Ausgabe für Docker Logs erzwingen
ENV PYTHONUNBUFFERED=1

# ==========================================
# LAYER 1: System-Pakete installieren
# ==========================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcom-err2 \
    python3-inotify \
    mc \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis setzen (Metadaten-Layer)
WORKDIR /app

# ==========================================
# LAYER 2: Verzeichnisse anlegen & Berechtigungen setzen
# ==========================================
RUN mkdir -p /media/in /media/out /log /etc/fetchbridge/conf.d && chmod 777 /media/in /media/out /log

# ==========================================
# LAYER 3: Skripte & Configs kopieren, ausführen & verlinken
# ==========================================
COPY --chmod=644 bashrc /etc/global.bashrc
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chmod=755 fetchbridge.py /usr/local/bin/fetchbridge
COPY --chmod=644 fetchbridge.conf.example /etc/fetchbridge/fetchbridge.conf

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/fetchbridge \
    && ln -s /etc/global.bashrc /tmp/.bashrc \
    && ln -s /etc/global.bashrc /app/.bashrc

ENV HOME=/app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

ARG VERSION
ARG BUILD_DATE

LABEL version="${VERSION}"
LABEL build_date="${BUILD_DATE}"
LABEL maintainer="Chaos7x"
LABEL purpose="Directory monitoring and automated video moving"
