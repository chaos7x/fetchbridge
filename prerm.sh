#!/bin/sh
# Wird von dpkg vor dem Entfernen des Pakets ausgefuehrt (fpm --before-remove).
# $1 = "remove" beim tatsaechlichen Entfernen, "upgrade" bei einem Update auf
# eine neue Version - der Dienst soll bei einem Upgrade weiterlaufen.
set -e

if [ "$1" = "remove" ]; then
    if [ -d /run/systemd/system ]; then
        systemctl stop fetchbridge.service || true
        systemctl disable fetchbridge.service || true
    elif [ -x /etc/init.d/fetchbridge ]; then
        /etc/init.d/fetchbridge stop || true
        command -v update-rc.d >/dev/null 2>&1 && update-rc.d fetchbridge remove >/dev/null || true
    fi
fi

exit 0
