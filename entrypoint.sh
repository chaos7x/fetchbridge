#!/bin/sh

# Prüfen, ob ein gültiger Systembefehl oder absoluter Pfad als erstes Argument übergeben wurde
if [ "$#" -gt 0 ] && ( [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 ); then
    exec "$@"
fi

# Docker startet den Recorder standardmäßig im Daemon-Modus, wenn keine Argumente übergeben werden
if [ "$#" -eq 0 ]; then
    set -- -D
fi

# Wenn ein externes Skript gemountet wurde, nutzen wir das
if [ -f /app/fetchbridge ]; then
    echo ">>> Using external fetchbridge from volume..."
    chmod +x /app/fetchbridge 2>/dev/null || true
    exec /app/fetchbridge "$@"
else
    # Andernfalls greifen wir auf das im Image eingebaute Skript zurück
    echo ">>> Using internal /usr/local/bin/fetchbridge from image..."
    exec /usr/local/bin/fetchbridge "$@"
fi
