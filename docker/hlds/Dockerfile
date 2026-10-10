# MapForge simulation server: HLDS (cstrike, SteamCMD anonymous, branch steam_legacy) with
# ReHLDS + ReGameDLL + Metamod-R + AMX Mod X + YaPB, headless. Built by mapforge.simulate from
# docker/hlds/ + server/plugins/ (no BuildKit features: the Docker SDK builds it).
# Nothing from here is committed: the game files and add-ons are downloaded at build time.

FROM debian:trixie-slim AS base
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl lib32gcc-s1 lib32stdc++6 libc6-i386 unzip xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m hlds
USER hlds
WORKDIR /home/hlds

# The game: SteamCMD needs several app_update runs before app 90 is complete.
FROM base AS game
RUN mkdir steamcmd \
    && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
        | tar -xz -C steamcmd \
    && for i in 1 2 3; do ./steamcmd/steamcmd.sh +force_install_dir /home/hlds/hlds \
        +login anonymous +app_set_config 90 mod cstrike +app_update 90 -beta steam_legacy validate \
        +quit || true; done \
    && test -f hlds/hlds_linux && test -f hlds/cstrike/liblist.gam \
    && grep -h '"buildid"' hlds/steamapps/appmanifest_90.acf > hlds/BUILD_INFO \
    && rm -rf hlds/steamapps/downloading

FROM base
COPY --from=game --chown=hlds /home/hlds/hlds /home/hlds/hlds
COPY --chown=hlds addons.lock install_addons.sh /tmp/addons/
RUN sh /tmp/addons/install_addons.sh /tmp/addons/addons.lock /home/hlds/hlds \
    && cat /tmp/addons/addons.lock >> /home/hlds/hlds/BUILD_INFO && rm -rf /tmp/addons
# steamclient.so where the Steam API looks for it; app id 10 = Counter-Strike
RUN mkdir -p .steam/sdk32 && ln -s /home/hlds/hlds/steamclient.so .steam/sdk32/steamclient.so \
    && echo 10 > hlds/steam_appid.txt

# Our AMXX plugins, compiled with the bundled amxxpc
COPY --chown=hlds plugins/ /tmp/plugins/
RUN cd hlds/cstrike/addons/amxmodx/scripting \
    && for f in /tmp/plugins/*.sma; do \
        n=$(basename "$f" .sma); \
        LD_LIBRARY_PATH=. ./amxxpc "$f" -o"../plugins/$n.amxx" && echo "$n.amxx" >> ../configs/plugins.ini || exit 1; \
    done && rm -rf /tmp/plugins

COPY --chown=hlds entrypoint.sh /home/hlds/entrypoint.sh
WORKDIR /home/hlds/hlds
EXPOSE 27015/udp
ENTRYPOINT ["bash", "/home/hlds/entrypoint.sh"]
