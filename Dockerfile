FROM debian:trixie-slim

# Ungepufferte Python-Ausgabe für Docker Logs erzwingen
ENV PYTHONUNBUFFERED=1

# ==========================================
# LAYER 1: System-Pakete + Pip-Installation
# ==========================================
# python3-inotify ist unter Debian das korrekte Paket (importiert als
# `inotify.adapters`) - kein --target nötig, Debians python3-pip installiert
# bereits automatisch nach /usr/local (FHS-konform gepatcht).
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-setuptools \
    python3-inotify \
    libcom-err2 \
    mc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV HOME=/app

# ==========================================
# LAYER 2: Verzeichnisse anlegen & Berechtigungen setzen
# ==========================================
# 1777 statt 777: die Laufzeit-UID ist unbekannt (frei wählbar via `docker run -u`,
# um Berechtigungskonflikte mit host-gemounteten Verzeichnissen zu vermeiden),
# daher müssen alle drei Verzeichnisse für jede UID beschreibbar bleiben. Das
# Sticky-Bit (wie bei /tmp) verhindert aber, dass ein Prozess/Nutzer Dateien
# löschen oder umbenennen kann, die ein anderer angelegt hat.
RUN mkdir -p /media/in /media/out /log /etc/fetchbridge/conf.d && chmod 1777 /media/in /media/out /log

# ==========================================
# LAYER 3: fetchbridge-Package installieren
# ==========================================
COPY pyproject.toml /app/pyproject.toml
COPY src/ /app/src/
RUN pip install --no-cache-dir --break-system-packages --no-deps . \
    && rm -rf /app/pyproject.toml /app/src /app/build

# ==========================================
# LAYER 4: Skripte & Configs kopieren
# ==========================================
COPY --chmod=644 bashrc /etc/global.bashrc
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chmod=644 fetchbridge.conf.example /etc/fetchbridge/fetchbridge.conf

RUN ln -s /etc/global.bashrc /tmp/.bashrc \
    && ln -s /etc/global.bashrc /app/.bashrc

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD ["fetchbridge", "--healthcheck"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

ARG VERSION
ARG BUILD_DATE

LABEL version="${VERSION}"
LABEL build_date="${BUILD_DATE}"
LABEL maintainer="Chaos7x"
LABEL purpose="Directory monitoring and automated video moving"
