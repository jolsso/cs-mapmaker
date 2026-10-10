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
  CT: {area: ct_spawn, count: 16}
buyzones: true                # func_buyzone over hvert spawn-område
```

## Hvad Decide kan ændre (fase 6)
Værktøjskassen i `config/fitness.yaml` peger på navne i spec'en: `move_corridor`/`resize_corridor` → et områdes `rect`; `adjust_opening` → en dørs `width`/`height`; `add_cover`/`remove_cover` → `cover`; `move_spawn` → spawn-område; `add_connection`/`remove_connection` → `doors`. Derfor skal alle navne være unikke.
