#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
EXAMPLE_FILE="$ROOT_DIR/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ ! -f "$EXAMPLE_FILE" ]]; then
    echo "No existe $EXAMPLE_FILE para crear $ENV_FILE." >&2
    exit 1
  fi
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Creado $ENV_FILE desde .env.example"
fi

backup="$ENV_FILE.backup.$(date +%Y%m%d%H%M%S)"
cp "$ENV_FILE" "$backup"
chmod 600 "$backup"

printf "Pega el token de Mapbox para KALMIO_MAPBOX_ACCESS_TOKEN: "
IFS= read -r -s token
printf "\n"

if [[ -z "${token// }" ]]; then
  echo "Token vacío; no se ha modificado $ENV_FILE." >&2
  exit 1
fi

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"

  if grep -q "^${key}=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" 'BEGIN { replaced=0 } {
      if ($0 ~ "^" key "=" && replaced == 0) {
        print key "=" value
        replaced=1
      } else {
        print
      }
    }' "$ENV_FILE" > "$tmp"
  else
    cp "$ENV_FILE" "$tmp"
    printf "%s=%s\n" "$key" "$value" >> "$tmp"
  fi

  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

set_env_value "KALMIO_GEOCODING_PROVIDER" "mapbox"
set_env_value "KALMIO_MAPBOX_ACCESS_TOKEN" "$token"
set_env_value "KALMIO_MAPBOX_GEOCODING_BASE_URL" "https://api.mapbox.com"
set_env_value "KALMIO_MAPBOX_SEARCH_API" "auto"
set_env_value "KALMIO_GEOCODING_COUNTRY" "ES"
set_env_value "KALMIO_GEOCODING_LANGUAGE" "es"
set_env_value "KALMIO_GEOCODING_TIMEOUT_SECONDS" "4"
set_env_value "KALMIO_GEOCODING_REQUEST_RETRIES" "1"
set_env_value "KALMIO_GEOCODING_LIMIT" "5"

echo "Mapbox configurado en $ENV_FILE"
echo "Backup local: $backup"
