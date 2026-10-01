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
# Stage 1:1 übernehmen kann. --no-deps: fetchbridge hat keine
# Laufzeit-Abhängigkeiten (inotify über eigenen ctypes-Wrapper).
#
# /rootfs: alles, was die Final-Stage aus dem Repo/Builder braucht, wird hier
# bereits im späteren Ziel-Layout zusammengestellt, damit die Final-Stage es
# mit EINEM einzigen COPY (= einem Layer) statt einem Layer pro Datei übernimmt.
# Die Zielverzeichnisse werden dabei VORHER per mkdir angelegt: COPY --chmod
# würde fehlende Elternverzeichnisse sonst mit demselben Modus anlegen, und
# COPY /rootfs/ / überträgt Verzeichnis-Modi auf das Ziel.
RUN pip install --break-system-packages --no-deps --no-cache-dir /build --target=/install \
    && mkdir -p /rootfs/usr/local/bin /rootfs/usr/local/lib/fetchbridge /rootfs/etc/fetchbridge \
    && mv /install/bin/fetchbridge /rootfs/usr/local/bin/ \
    && mv /install/fetchbridge /rootfs/usr/local/lib/fetchbridge/ \
    && mv /install/fetchbridge-*.dist-info /rootfs/usr/local/lib/fetchbridge/fetchbridge.dist-info
COPY --chmod=644 bashrc /rootfs/etc/global.bashrc
COPY --chmod=755 entrypoint.sh /rootfs/usr/local/bin/entrypoint.sh
COPY --chmod=644 fetchbridge.conf.example /rootfs/etc/fetchbridge/fetchbridge.conf

# ==========================================
# STUFE 2: FINAL STAGE (schlankes Laufzeit-Image, kein pip/setuptools)
# ==========================================
FROM debian:trixie-slim

# Ungepufferte Python-Ausgabe für Docker Logs erzwingen. PYTHONPATH macht das
# Package unabhängig von distro-spezifischen site-packages-Konventionen
# auffindbar.
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    HOME=/app \
    PYTHONPATH=/usr/local/lib/fetchbridge

# ==========================================
# LAYER 1: System-Pakete, User, Verzeichnisse & Symlinks in EINEM Rutsch
# ==========================================
# Ein einziges RUN statt mehrerer = ein Layer statt fünf.
#
# Pakete: Bewusst OHNE pip/setuptools - die werden nur im Builder (STUFE 1)
# gebraucht.
# apt-get upgrade: das Base-Image selbst (Pakete wie gzip/perl-base/libssl3/
# libsqlite3/libpcre2, die nicht über unsere eigenen apt-get-install-Zeilen
# kommen) hinkt Debians eigenen Security-Patches oft ein paar Tage hinterher,
# bis die Docker-Official-Images-Pipeline es neu baut - ein simples `docker
# pull` holt dann weiterhin die alte, unpatchte Version. apt-get upgrade
# zieht stattdessen bei jedem Build die aktuell in Debians eigenen Repos
# verfügbaren Paketversionen, unabhängig vom Alter des Base-Images selbst.
#
# Non-Root-User: Gehärtetes Image, laeuft standardmaessig nicht als root,
# auch wenn beim Deploy kein `user:`/`-u` gesetzt wird. UID/GID bewusst NICHT
# fest kodiert - useradd/groupadd (statt adduser, das im -slim-Base-Image
# fehlt und den Build mit "exit code: 127" scheitern liess) waehlen
# automatisch eine freie System-UID <1000. Wer die UID an sein eigenes Setup
# anpassen will (z.B. fuer Bind-Mount-Rechte), ueberschreibt sie ganz normal
# per `docker run -u`/Compose `user:` - die 1777-Verzeichnisse bleiben davon
# unabhaengig fuer jede UID beschreibbar.
#
# 1777 statt 777: die Laufzeit-UID ist unbekannt (frei wählbar via `docker run -u`,
# um Berechtigungskonflikte mit host-gemounteten Verzeichnissen zu vermeiden),
# daher müssen alle drei Verzeichnisse für jede UID beschreibbar bleiben. Das
# Sticky-Bit (wie bei /tmp) verhindert aber, dass ein Prozess/Nutzer Dateien
# löschen oder umbenennen kann, die ein anderer angelegt hat.
#
# /app gehoert dem dedizierten User statt root, damit HOME=/app (siehe oben)
# fuer ihn tatsaechlich beschreibbar ist.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    python3 \
    libcom-err2 \
    mc \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system fetchbridge \
    && useradd --system --no-create-home --home /nonexistent \
        --shell /usr/sbin/nologin --gid fetchbridge fetchbridge \
    && mkdir -p /log /etc/fetchbridge/conf.d /srv/media-pipeline/recordings /srv/media-pipeline/incoming \
    && chmod 1777 /log /srv/media-pipeline/recordings /srv/media-pipeline/incoming \
    && ln -s /etc/global.bashrc /tmp/.bashrc \
    && ln -s /etc/global.bashrc /app/.bashrc \
    && chown fetchbridge:fetchbridge /app

# ==========================================
# LAYER 2: fetchbridge-Package, Skripte & Configs aus dem Builder
# ==========================================
# Liegen in /rootfs (STUFE 1) bereits im Ziel-Layout - ein COPY, ein Layer,
# kein pip-Aufruf in dieser Stage. Steht bewusst NACH dem RUN oben, damit
# eine reine Code-Änderung den Paket-Layer aus dem Cache weiterverwendet.
COPY --from=builder /rootfs/ /

USER fetchbridge

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD ["fetchbridge", "--healthcheck"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

ARG VERSION
ARG BUILD_DATE

LABEL version="${VERSION}" \
      build_date="${BUILD_DATE}" \
      maintainer="Chaos7x" \
      purpose="Directory monitoring and automated video moving"
