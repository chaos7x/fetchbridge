#!/bin/sh

# Prüfen, ob ein gültiger Systembefehl oder absoluter Pfad als erstes Argument übergeben wurde
if [ "$#" -gt 0 ] && ( [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 ); then
    exec "$@"
fi

# Docker startet fetchbridge standardmäßig im Daemon-Modus, wenn keine Argumente übergeben werden
if [ "$#" -eq 0 ]; then
    set -- -D
fi

# Wenn ein externes Skript gemountet wurde, nutzen wir das - aber nur, wenn es
# nicht gruppen-/weltweit beschreibbar ist. Ohne diese Prüfung würde JEDE
# Datei, die es irgendwie schafft, unter /app/fetchbridge zu landen (z.B. ein
# falsch konfiguriertes/kompromittiertes Volume), bei jedem Container-Neustart
# automatisch mit vollen Container-Rechten ausgeführt. Die Prüfung läuft über
# python3 (immer im Image vorhanden) statt über `stat`, dessen Flags sich
# zwischen GNU/coreutils (Debian/Dockerfile.pyimg) und BusyBox (Alpine)
# unterscheiden.
if [ -f /app/fetchbridge ]; then
    if python3 -c "
import os, stat, sys
st = os.stat('/app/fetchbridge')
sys.exit(1 if stat.S_IMODE(st.st_mode) & (stat.S_IWGRP | stat.S_IWOTH) else 0)
"; then
        echo ">>> Using external fetchbridge from volume..."
        chmod +x /app/fetchbridge 2>/dev/null || true
        exec /app/fetchbridge "$@"
    else
        echo ">>> WARNING: /app/fetchbridge exists but is group- or world-writable - refusing to execute it for safety. Falling back to internal script." >&2
    fi
fi

# Andernfalls (kein externes Skript, oder oben abgelehnt) greifen wir auf das
# im Image eingebaute Skript zurück. Bewusst ohne hartkodierten Pfad
# (PATH-Auflösung statt /usr/local/bin): pip installiert Entry-Points je nach
# Distro an unterschiedliche Stellen (Debian: /usr/local/bin per eigener
# Konvention, Alpine: /usr/bin bzw. hier explizit nach /usr/local/bin kopiert
# - PATH-Auflösung macht die Annahme überflüssig).
echo ">>> Using internal fetchbridge from image..."
exec fetchbridge "$@"
