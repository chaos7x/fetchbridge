#!/bin/sh
# Wird von dpkg nach dem Entpacken des .deb ausgefuehrt (fpm --after-install).
set -e

if ! getent passwd fetchbridge >/dev/null 2>&1; then
    adduser --system --group --no-create-home --home /nonexistent \
        --shell /usr/sbin/nologin fetchbridge
fi

# Gemeinsame Gruppe fuer die Uebergabeverzeichnisse der Pipeline
# (tw-recorder -> fetchbridge -> yt-upload). Jedes der drei .deb-Pakete legt
# Gruppe und Verzeichnisse unabhaengig und idempotent an, da die Installationsreihenfolge
# nicht garantiert ist. 2775 + setgid, damit jedes Mitglied neu angelegte
# Dateien des jeweils anderen Dienstes auch wieder verschieben/loeschen kann
# (dafuer reicht Schreibrecht auf das Verzeichnis, unabhaengig vom Datei-Owner).
if ! getent group media-pipeline >/dev/null 2>&1; then
    addgroup --system media-pipeline
fi
adduser fetchbridge media-pipeline

mkdir -p /srv/media-pipeline/recordings /srv/media-pipeline/incoming
chown root:media-pipeline /srv/media-pipeline /srv/media-pipeline/recordings /srv/media-pipeline/incoming
chmod 2775 /srv/media-pipeline /srv/media-pipeline/recordings /srv/media-pipeline/incoming

# /run/systemd/system existiert nur, wenn systemd tatsaechlich als Init-System
# laeuft (nicht z.B. in einem Chroot/Container-Build ohne systemd) - ohne
# diese Absicherung wuerde die Paketinstallation dort fehlschlagen.
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi

echo ""
echo "fetchbridge wurde installiert, der systemd-Service ist aber noch NICHT aktiviert."
echo "Bitte zuerst /etc/fetchbridge/fetchbridge.conf (source_dir/target_dir) anpassen,"
echo "dann den Dienst manuell aktivieren und starten:"
echo ""
echo "    systemctl enable --now fetchbridge"
echo ""

exit 0
