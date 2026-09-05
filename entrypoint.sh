#!/bin/sh

# Wenn ein externes Skript gemountet wurde, nutzen wir das
if [ -f /app/mover ]; then
    echo ">>> Using external mover from volume..."
    chmod +x /app/mover 2>/dev/null || true
    exec /app/mover "$@"
else
    # Andernfalls greifen wir auf das im Image eingebaute Skript zurück
    echo ">>> Using internal /usr/local/bin/mover from image..."
    exec /usr/local/bin/mover "$@"
fi
