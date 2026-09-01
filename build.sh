#!/usr/bin/env bash
set -e

# Version aus erstem Argument übernehmen oder Fallback auf 'dev'
VERSION="${1:-dev}"
BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
NAME="mediadog"

echo "Baue Docker-Image (Name: $NAME, Version: $VERSION)..."

# Tag-Liste initialisieren
TAGS=(-t "$NAME:$VERSION")

# Tag 'latest' nur hinzufügen, wenn es sich NICHT um ein 'dev'-Build handelt
if [ "$VERSION" != "dev" ]; then
  TAGS+=(-t "$NAME:latest")
fi

docker build -f Dockerfile \
  --build-arg VERSION="$VERSION" \
  --build-arg BUILD_DATE="$BUILD_DATE" \
  --pull \
  "${TAGS[@]}" .

echo "Fertig!"
