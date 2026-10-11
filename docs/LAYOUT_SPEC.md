# Layout-spec (`maps/<map>/layout.yaml`)

Kilden til et genereret map. `./mf generate MAP=<map>` skriver `maps/<map>/src/<map>.map` (genereret – redigér aldrig den direkte). Alle koordinater er heltal på `grid` (standard 16). 1 unit ≈ 1 inch; en spiller er 32×32×72.

## Princip
Spec'en beskriver kun **tomt rum**: områder (rum, korridorer, udendørs pladser) og døre mellem dem. Alt andet inden for en ydre skal er solidt. Derfor kan et genereret map ikke lække, og alle vertices ligger på grid'et. Områder adskilles af præcis én væg (`wall`, standard 16 units); en dør skærer et hul i den væg.

```
 ┌─────────┐16┌─────────┐       område = tomt rum (rect × floor..floor+height)
 │ t_spawn ├──┤   mid   │       dør    = hul i væggen mellem to områder
 └─────────┘  └─────────┘       alt andet inden for skallen = solidt
```

## Felter

```yaml
name: de_forge01              # = mappens mappenavn
grid: 16                      # alle tal skal gå op i grid
wall: 16                      # vægtykkelse mellem områder og i den ydre skal
textures:                     # valgfrit; standard er dev-WAD'ens teksturer
  floor: DEV_FLOOR
  wall: DEV_WALL
  ceiling: DEV_CEIL
  cover: DEV_CRATE
  sky: SKY
  trigger: AAATRIGGER
sky:                          # gælder områder med outdoor: true
  name: desert                # skybox (gfx/env/<name>*.tga i spillet)
  sun: {pitch: -50, yaw: 135, color: [255, 240, 215], brightness: 280, ambient: 90}
lights:                       # punktlys i indendørs områder, jævnt fordelt
  spacing: 384
  brightness: 220
  color: [255, 236, 210]

areas:                        # tomt rum
  - name: t_spawn
    rect: [x0, y0, x1, y1]    # grundplan
    floor: 0                  # gulvhøjde (z)
    height: 192               # loftshøjde over gulvet (norm: >= 96, korridorer >= 128)
    outdoor: false            # true = himmel i stedet for loft (sol fra sky.sun)
    role: t_spawn             # beskrivende: t_spawn, ct_spawn, site, corridor, mid, room

doors:                        # hul i væggen mellem to områder, der ligger én væg fra hinanden
  - name: t_spawn_to_mid
    between: [t_spawn, mid]
    width: 160                # norm: >= 64 (validatoren advarer under)
    height: 160               # valgfrit; standard = op til det laveste loft
    offset: 0                 # forskydning langs væggen fra midten af den fælles væg

stairs:                       # trin bygget ind i et område (fx op til et hævet site)
  - name: a_steps
    area: a_ramp
    axis: +y                  # retning man går OP ad
    rise: 64                  # samlet stigning (multiplum af step)
    step: 16                  # højde pr. trin (<= 18, GoldSrc stepsize)
    run: 32                   # dybde pr. trin
    start: 0                  # afstand fra områdets kant til første trin
                              # efter sidste trin er resten af området hævet med `rise`

cover:                        # kasser/vægge inde i et område
  - name: a_crates
    area: a_site
    pos: [x, y]               # centrum
    size: [w, d, h]

sites: {A: a_site, B: b_site} # område pr. bomb site (func_bomb_target, 32 units inde fra væggene)
spawns:
  T:  {area: t_spawn, count: 16}   # standard 16 (spillets maks.); gitter med 64 units mellemrum, 8 units over gulvet, vendt mod midten
                                   # offset: [dx, dy] (valgfri) flytter klyngens centrum inde i området (Decide: move_spawn)
  CT: {area: ct_spawn, count: 16}
buyzones: true                # func_buyzone over hvert spawn-område
```

## Udvidet geometri og entiteter (2026-10-11)
Alt er valgfrit; et layout uden disse nøgler genereres byte for byte som før.

```yaml
detail: true                  # cover, trapper, ramper og kiler i én func_detail (SDHLT): blokerer og lyses
                              # som world, men splitter ikke vis-leaves (færre leaves, hurtigere VIS)
zones:                        # identitet/callouts: tekstur- og lyssæt pr. zone
  a: {floor: DEV_FLOOR_RED, wall: DEV_WALL_RED, ceiling: DEV_CEIL_RED, cover: DEV_METAL,
      light: {color: [255, 200, 180], brightness: 240}}
areas:
  - {name: a_site, rect: [...], zone: a}   # hver skalflade får teksturen fra det område, den vender ind mod

doors:
  - name: mid_a_window
    between: [mid, a_site]
    width: 96
    kind: window              # door (standard) | window (hul fra `sill`; kig/skyd igennem, ikke en rute)
                              # | vent (kravle-rute: height 40..64)
    sill: 80                  # bund over det højeste af de to gulve (window: >= 64)
    height: 64
    glass: true               # func_breakable-glas i hullet (material glass, rendermode texture)
  - {name: t_gate, between: [t_spawn, mid], width: 128, gate: sliding}  # func_door (glider op, lukker efter 3 s)
                              # gate: rotating = func_door_rotating med ORIGIN-hængsel i hullets ene ende

ramps:                        # skråt gulv over hele områdets bredde (<= 45°: rise <= length)
  - {name: a_ramp, area: a_site, axis: +y, rise: 64, length: 128, start: 128}
                              # efter rampen er resten af området hævet med `rise` (som stairs)
wedges:                       # solid trekant i et hjørne: hypotenusen er en skrå væg
  - {name: b_chamfer, area: b_site, corner: sw, size: [192, 192]}   # ne|nw|se|sw, kateter langs x og y
                              # (lige lange = 45°). To modsatte kiler gør et rektangel til en skrå korridor
stairs:
  - {name: ct_steps, area: ct_spawn, axis: +x, rise: 32, start: 448, clip: true}
                              # clip: player-clip-rampe på trinenes forkanter (glat bevægelse)
cover:
  - {name: b_ledge, area: b_site, pos: [x, y], size: [128, 128, 16], z: 112}
                              # z = bund over gulvet: platforme, broer, catwalks, stablede kasser (boost)
  - {name: a_pillar, area: a_site, pos: [x, y], size: [64, 64, 288], texture: DEV_METAL}
ladders:                      # stige mod en væg: func_illusionary (DEV_LADDER) + func_ladder-volumen, 8 dyb
  - {name: b_ladder, area: b_site, wall: +x, pos: -96, width: 32, height: 128}
weapons:                      # armoury_entity på gulvet: item = navn (awp, ak47, kevlar, hegrenade …) eller nummer
  - {area: mid, pos: [0, 0], item: awp, count: 1}
map_parameters: {buying: both, bombradius: 500}   # info_map_parameters: buying both|ct|t|none
```

**Dev-WAD:** ud over grundsættet har `mapforge_dev.wad` tool-teksturerne `CLIP` og `ORIGIN`, entitetsteksturerne `DEV_GLASS`, `DEV_DOOR` og `DEV_LADDER`, zone-tints `DEV_{FLOOR,WALL,CEIL}_{RED,BLUE,GREEN,SAND,GREY}` og landmark-materialerne `DEV_METAL`, `DEV_BRICK`, `DEV_CONCRETE` og `DEV_WOOD`. Alt er proceduralt og vores eget arbejde (CC0).

**Flere niveauer:** områder må ligge over hinanden (forskellig `floor`, ingen overlap i højden), og et cover med `z` er en bro eller catwalk i et højt rum. Ladders, ramper og vinduer forbinder niveauerne. Validatorens gangbarhedsgraf arbejder på den compilede BSP (hulls, hop, crouch og func_ladder), så den forstår niveauerne uden særregler.

**Ikke-rektangulære rum:** to områder, der rører hinanden (ingen væg imellem), bliver ét rum, fx et L-rum eller et rum med forskellig lofthøjde. Kiler skærer hjørner skråt af.

## Sjæl: koncept, landemærker, chokes, brud (DESIGN_GUIDE.md §9)
Felter, som generatoren ignorerer, men som Review (rubrikken) og Decide læser, og som loopet ikke må optimere væk:

```yaml
concept: "Mid-tungt map: mid_top er nøglen, B er et tæt indendørs fort"   # én sætning (servietprøven)
archetype: three_lane            # three_lane | asymmetric | stacked
landmarks:                       # ét unikt, navngiveligt træk pr. zone → callouts
  - {name: Søjlerne, element: b_pillar_w, zone: b_site, function: "callout; bryder sigtelinjen CT-dør → tunnel"}
chokes:                          # ét pr. hovedvej, før sitet
  - {name: Long-døren, door: d_long_n2, type: doorway, engagement: long, utility: smoke}
irregularities:                  # bevidste brud på grid-rytmen, med gameplay-formål
  - {element: b_platform, purpose: "lav platform giver post-plant-højde"}
intended_strategies:             # mindst 3 T-planer og 2 CT-setups, som playtest/Review tester imod
  T: ["rush B gennem tunnelerne", "mid-kontrol → split A short + long", "fake A long, rotér via mid_to_b"]
  CT: ["2-1-2 (A, mid_top, B)", "stack A, retake B via ct_to_b"]
style_rules:                     # regler art pass (fase 7) bindes af, fx Johnstons trim-regler
  - "trim aldrig på gulv/loft, højst to gange pr. væg"
```

Navne i `landmarks[].element`, `irregularities[].element` og `chokes[].door` er låst: `apply.py` afviser at flytte, fjerne eller ændre dem (som `protected`).

## Beskyttede elementer
`protected: true` på et område, en dør eller et cover betyder, at loopet aldrig flytter, ændrer størrelse på eller fjerner det (låst topologi, fx chokepoint-dørene i de_forge01). Områder med `role: site`, `t_spawn` eller `ct_spawn` er altid låste (site-placeringer, FITNESS).

## Hvad Decide kan ændre (fase 6)
Værktøjskassen i `config/fitness.yaml` peger på navne i spec'en: `move_corridor`/`resize_corridor` → et områdes `rect`; `adjust_opening` → en dørs `width`/`height`; `add_cover`/`remove_cover` → `cover`; `move_spawn` → spawn-område; `add_connection`/`remove_connection` → `doors`; `remove_area` (kun på et menneskes annotation) → fjerner et område med dets døre, cover og trapper. Fra 2026-10-11 også: `add_cover` med `z`/`texture`; `add_connection` med `kind: vent`; `add_window` → en dør med `kind: window`; `set_gate` → en dørs `gate`; `add_ramp` → `ramps`; `add_wedge` → `wedges`; `add_ladder` → `ladders`; `remove_element` → fjerner en rampe, kile, stige, cover, trappe eller et vindue ved navn. `add_area` må ligge over/under et andet område (adskilt i højden). Derfor skal alle navne være unikke. Ændringerne anvendes af `mapforge/loop/apply.py` med round-trip-YAML (kommentarer bevares); hver ændring prøve-genereres, og en ændring, der ikke kan bygges (fx en dør mister sin fælles væg), springes over med begrundelse.
