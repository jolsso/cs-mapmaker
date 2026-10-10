#!/bin/bash
# Start one simulation server. The runner (mapforge.simulate) copies the map, cfg files and
# (if cached) the YaPB graph into the container before starting it, and sets:
#   MF_MAP, MF_RUN_ID, MF_MAXPLAYERS, MF_TICRATE, MF_DEMO (1 = record an HLTV demo)
# The tracker plugin quits the server after mf_max_rounds rounds (see mapforge.cfg).
set -u
cd /home/hlds/hlds
cs=cstrike
conf=$cs/addons/yapb/conf
# our YaPB settings replace the shipped lines (YaPB keeps the first value of a cvar it reads)
awk 'NR == FNR { if ($1 !~ /^\/\//) mine[$1] = 1; next } !($1 in mine)' \
    "$conf/mapforge_yapb.cfg" "$conf/yapb.cfg.orig" > "$conf/yapb.cfg"
cat "$conf/mapforge_yapb.cfg" >> "$conf/yapb.cfg"
mkdir -p "$cs/logs/mapforge" "$cs/demos"

# Console input through FIFOs held open here, so the servers never read EOF.
mkfifo /tmp/hlds_in /tmp/hltv_in
exec 3<>/tmp/hlds_in 4<>/tmp/hltv_in
export LD_LIBRARY_PATH=.

./hlds_linux -game cstrike -port 27015 -sys_ticrate "$MF_TICRATE" +ip 0.0.0.0 \
    +maxplayers "$MF_MAXPLAYERS" +sv_lan 1 +map "$MF_MAP" <&3 &
hlds=$!
trap 'kill $hlds 2>/dev/null' TERM INT

hltv=""
if [ "${MF_DEMO:-0}" = "1" ]; then
    sleep 5
    ./hltv -port 27020 +delay 0 +connect 127.0.0.1:27015 +record "demos/$MF_RUN_ID" <&4 &
    hltv=$!
fi

wait $hlds
code=$?
if [ -n "$hltv" ]; then
    echo stoprecording >&4
    echo quit >&4
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 $hltv 2>/dev/null || break; sleep 1; done
    kill $hltv 2>/dev/null
fi
exit $code
