FROM debian:trixie-slim

ARG VERSION
ARG BUILD_DATE

LABEL version="${VERSION}"
LABEL build_date="${BUILD_DATE}"
LABEL maintainer="Chaos7x"
LABEL purpose="Directory monitoring and automated video moving"

# Ungepufferte Python-Ausgabe für Docker Logs erzwingen
ENV PYTHONUNBUFFERED=1

# ==========================================
# STUFE 2: System-Pakete & Python-Inotify
# ==========================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcom-err2 \
    python3-inotify \
    mc \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# STUFE 4: Arbeitsverzeichnis & Mount-Pfade
# ==========================================
WORKDIR /app

# Die Standardpfade für in/out
RUN mkdir -p /media/in /media/out /log && \
    chmod 777 /media/in /media/out /log

# ==========================================
# STUFE 5: Skripte kopieren & Rechte setzen
# ==========================================
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY mover.py /usr/local/bin/mover

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/mover

# Systemkonfiguration (.bashrc)
COPY bashrc /etc/global.bashrc
RUN ln -s /etc/global.bashrc /tmp/.bashrc && \
    ln -s /etc/global.bashrc /app/.bashrc

ENV HOME=/app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
