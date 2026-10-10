#!/bin/sh
# Download the pinned add-ons (addons.lock), verify SHA256 and install them into the HLDS tree.
# Usage: install_addons.sh <addons.lock> <hlds dir>
set -eu
lock=$1
hlds=$2
dl=$(mktemp -d)

grep -v '^#' "$lock" | grep -v '^[[:space:]]*$' | while read -r name url sha; do
    file="$dl/$name.${url##*/}"
    curl -fsSL "$url" -o "$file"
    echo "$sha  $file" | sha256sum -c -
done

get() { ls "$dl/$1".*; }
cs="$hlds/cstrike"

# ReHLDS: engine binaries (linux32) over the Valve ones
unzip -q "$(get rehlds)" 'bin/linux32/*' -d "$dl/rehlds"
cp -r "$dl/rehlds/bin/linux32/." "$hlds/"
# ReGameDLL: game library + its config
unzip -q "$(get regamedll)" 'bin/linux32/*' -d "$dl/regamedll"
cp -r "$dl/regamedll/bin/linux32/cstrike/." "$cs/"
# Metamod-R, loaded instead of the game library
unzip -q "$(get metamod)" 'addons/*' -d "$cs"
sed -i 's|^gamedll_linux .*|gamedll_linux "addons/metamod/metamod_i386.so"|' "$cs/liblist.gam"
# AMX Mod X (base + cstrike modules) and YaPB
tar -xzf "$(get amxx_base)" -C "$cs"
tar -xzf "$(get amxx_cs)" -C "$cs"
tar -xJf "$(get yapb)" -C "$cs"
mkdir -p "$cs/addons/yapb/data/train" "$cs/addons/yapb/data/graph"
cp "$cs/addons/yapb/conf/yapb.cfg" "$cs/addons/yapb/conf/yapb.cfg.orig"
printf 'linux addons/amxmodx/dlls/amxmodx_mm_i386.so\nlinux addons/yapb/bin/yapb.so\n' \
    > "$cs/addons/metamod/plugins.ini"

rm -rf "$dl"
