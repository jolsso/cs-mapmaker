# Tracker-plugin – specifikation

AMX Mod X-plugin (`server/plugins/mapforge_tracker.sma`) der logger spillerposition og events til CSV for analyse.

✅ Natives og forwards verificeret mod AMX Mod X 1.10 (git5486) include-filerne, og pluginet compiler uden advarsler med den medfølgende `amxxpc` (2026-10-10). Bruger amxmodx, fakemeta og csx (`client_damage`, `client_death`, `bomb_planted/defused/explode`). Runder: logevent `Round_Start` (slut på freezetime = t 0), `TextMsg` `#Terrorists_Win`/`#CTs_Win`/`#Target_Bombed`/`#Bomb_Defused`/`#Target_Saved`/`#Round_Draw`; `Restart_Round_`/`Game_Commencing` kasserer den løbende runde.

## Krav
- Påvirker ikke gameplay.
- Logger kun bots på T og CT. Menneskelige spillere og spectators (fx dig, der kigger med) logges ikke i `positions.csv`/`events.csv`.
- Er et menneske på T eller CT i en runde, markeres runden med `humans_on_team > 0` i `rounds.csv`, og analysen udelader den.
- Lavt overhead: sampling via task, buffer i hukommelsen, flush ved rundeslut.
- Én CSV-mappe pr. server-run: `logs/mapforge/<map>_<run_id>/`.
- Konfiguration via cvars.

## Cvars
| Cvar | Default | Beskrivelse |
|---|---|---|
| `mf_enabled` | 1 | Tænd/sluk |
| `mf_sample_interval` | 0.5 | Sekunder mellem positionssamples |
| `mf_run_id` | "" | Sættes af runner |
| `mf_max_rounds` | 0 | 0 = ubegrænset; ellers skift/stop efter N runder |

## Filer og skema

### `positions.csv`
| Kolonne | Type | Beskrivelse |
|---|---|---|
| run_id | str | |
| round | int | Rundenummer i run |
| t | float | Sekunder siden rundestart |
| player_id | int | Slot |
| team | str | T / CT |
| alive | int | 0/1 |
| x, y, z | float | Origin |
| yaw, pitch | float | View-angles |
| hp | int | |
| weapon | str | Aktivt våben |

### `events.csv`
| Kolonne | Type | Beskrivelse |
|---|---|---|
| run_id | str | |
| round | int | |
| t | float | |
| type | str | `kill`, `damage`, `bomb_plant`, `bomb_defuse`, `bomb_explode`, `round_end`, `first_contact` |
| actor_id | int | Fx killer |
| actor_team | str | |
| target_id | int | Fx victim (tom hvis n/a) |
| target_team | str | |
| ax, ay, az | float | Actor-position |
| tx, ty, tz | float | Target-position |
| weapon | str | |
| extra | str | JSON: fx `{"site":"A"}`, `{"winner":"CT","reason":"defuse"}` |

`first_contact`: første gang en spiller tager skade fra modstander i runden (beregnes også i analyse som fallback).

### `rounds.csv`
| Kolonne | Type |
|---|---|
| run_id, round | |
| start_time, end_time | float (server-tid) |
| winner | T / CT |
| reason | elimination / bomb / defuse / time |
| plant_site | A / B / tom |
| t_alive_end, ct_alive_end | int |
| humans_on_team | int (0 = ren bot-runde; > 0 = ugyldig til metrikker) |
| t_players, ct_players | int (spillere pr. hold ved rundestart; runden tæller kun med fulde hold) |

`plant_site`: bogstavet fra `targetname` `site_<X>` på det bomb target, planteren står i; ellers tomt, og runneren udfylder det ud fra BSP'ens bomb sites (samme gruppering som validate). En runde tæller til metrikker, når den har en vinder, `humans_on_team == 0` og begge hold var fulde (`mapforge.simulate.records.valid_round`).

## Runner-integration
1. Runneren (`mapforge.simulate`) skriver `cstrike/mapforge.cfg` (cvars fra `config/pipeline.yaml` → `simulate.cvars` + `mf_run_id`, `mf_max_rounds`, `sys_timescale`); pluginet exec'er den i `plugin_cfg`, så dets egne cvars findes.
2. Server kører; plugin flusher pr. runde.
3. Ved `mf_max_rounds` færdige runder: plugin skriver `DONE` og sender `quit`; containeren stopper selv, og runneren henter filerne (`get_archive`).
4. Runneren validerer CSV mod skemaet (`mapforge.simulate.records`, kolonner + typer + tilladte værdier) før analyse.

## Bot-opsætning (server cfg)
- YaPB: fuldt hold (fx 5v5), fast difficulty, `mp_autoteambalance 1`, `mp_freezetime` kort, `mp_roundtime` fast.
- Seed eller variation: kør flere runs med forskellig difficulty for robusthed.
- ✅ YaPB 4.4.957: cvars tjekket mod den medfølgende `addons/yapb/conf/yapb.cfg`. Grafen laves automatisk (`yb_graph_analyze_auto_start 1`, `..._auto_save 1`), når der ikke findes en; runneren cacher den pr. .bsp-hash i `build/<map>/yapb/`. Download/upload af grafer er slået fra (`yb_graph_url ""`, `yb_graph_url_upload ""`), så intet om vores maps forlader maskinen.

## Test
- Plugin compiler med `amxxpc` i CI/Docker.
- Smoke test: 3 runder på test_box → CSV-filer findes, rækker > 0, skema valid.
