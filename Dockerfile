# ==========================================
# STUFE 1: Builder - installiert fetchbridge isoliert per pip
# ==========================================
# Eigene Stage, damit pip/setuptools NICHT im finalen Laufzeit-Image landen -
# nur das fertig installierte Package wird per COPY --from übernommen.
FROM debian:trixie-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-setuptools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml /build/pyproject.toml
COPY src/ /build/src/
# --target statt eines normalen `pip install` in system site-packages:
# liefert reine Python-Dateien flach in einem eigenen Ordner, den die finale
# Stage 1:1 übernehmen kann. --no-deps, da inotify unter Debian bewusst über
# apt (python3-inotify) kommt, nicht über pip (siehe LAYER 2 der Final-Stage).
RUN pip install --break-system-packages --no-deps --no-cache-dir /build --target=/install

# ==========================================
# STUFE 2: FINAL STAGE (schlankes Laufzeit-Image, kein pip/setuptools)
# ==========================================
FROM debian:trixie-slim

# Ungepufferte Python-Ausgabe für Docker Logs erzwingen
ENV PYTHONUNBUFFERED=1

# ==========================================
# LAYER 1: System-Pakete
# ==========================================
# python3-inotify ist unter Debian das korrekte Paket (importiert als
# `inotify.adapters`). Bewusst OHNE pip/setuptools - die werden nur im
# Builder (STUFE 1) gebraucht.
# apt-get upgrade: das Base-Image selbst (Pakete wie gzip/perl-base/libssl3/
# libsqlite3/libpcre2, die nicht über unsere eigenen apt-get-install-Zeilen
# kommen) hinkt Debians eigenen Security-Patches oft ein paar Tage hinterher,
# bis die Docker-Official-Images-Pipeline es neu baut - ein simples `docker
# pull` holt dann weiterhin die alte, unpatchte Version. apt-get upgrade
# zieht stattdessen bei jedem Build die aktuell in Debians eigenen Repos
# verfügbaren Paketversionen, unabhängig vom Alter des Base-Images selbst.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    python3 \
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
# LAYER 3: fetchbridge-Package aus dem Builder übernehmen
# ==========================================
# /install/bin und /install/fetchbridge* kommen fertig installiert aus der
# Builder-Stage (STUFE 1) - kein pip-Aufruf mehr in dieser Stage. PYTHONPATH
# macht das Package unabhängig von distro-spezifischen site-packages-
# Konventionen auffindbar.
COPY --from=builder /install/bin/fetchbridge /usr/local/bin/fetchbridge
COPY --from=builder /install/fetchbridge /usr/local/lib/fetchbridge/fetchbridge
COPY --from=builder /install/fetchbridge-*.dist-info /usr/local/lib/fetchbridge/fetchbridge.dist-info
ENV PYTHONPATH=/usr/local/lib/fetchbridge

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
