# Tracker-plugin – specifikation

AMX Mod X-plugin (`server/plugins/mapforge_tracker.sma`) der logger spillerposition og events til CSV for analyse.

⚠️ VERIFICÉR alle AMXX-natives og event-navne mod AMXX-dokumentationen og den installerede version (amxmodx, fakemeta, hamsandwich, evt. ReAPI).

## Krav
- Påvirker ikke gameplay.
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

## Runner-integration
1. Runner sætter `mf_run_id` og `mf_max_rounds` via server.cfg eller rcon.
2. Server kører; plugin flusher pr. runde.
3. Ved `mf_max_rounds` nået: plugin skriver `DONE`-fil og runner stopper containeren.
4. Runner validerer CSV mod skema (Python, fx pydantic/pandera) før analyse.

## Bot-opsætning (server cfg)
- YaPB: fuldt hold (fx 5v5), fast difficulty, `mp_autoteambalance 1`, `mp_freezetime` kort, `mp_roundtime` fast.
- Seed eller variation: kør flere runs med forskellig difficulty for robusthed.
- ⚠️ VERIFICÉR YaPB-cvars og kommandoer i yapb.readthedocs.io.

## Test
- Plugin compiler med `amxxpc` i CI/Docker.
- Smoke test: 3 runder på test_box → CSV-filer findes, rækker > 0, skema valid.
