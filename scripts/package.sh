#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-$PWD/stt-caption-kv260.tar.xz}"
REV="2cdfd21bb3decb7be02ccf7b5d21c33c8b92b5b0"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

PKG="$STAGE/stt-caption-install"
mkdir -p "$PKG"

cp -r app build/hw/kv260/stt-kv260 \
      data/export/quartznet_engine.bin data/export/running_prior.json \
      scripts/stt-caption scripts/stt-caption.conf scripts/stt-caption.service \
      scripts/install.sh scripts/uninstall.sh "$PKG/"
# The cpu runner's weights, so RUNNER=cpu works on the board
[ -e data/export/quartznet_int8.bin ] && cp data/export/quartznet_int8.bin "$PKG/"

curl -fsSL "https://github.com/ikwzm/udmabuf/archive/${REV}.tar.gz" | tar xz -C "$PKG"
mv "$PKG/udmabuf-$REV" "$PKG/u-dma-buf"

tar cJf "$OUT" -C "$STAGE" stt-caption-install
