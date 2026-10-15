# Layout-spec (`maps/<map>/layout.yaml`)

Kilden til et genereret map. `./mf generate MAP=<map>` skriver `maps/<map>/src/<map>.map` (genereret – redigér aldrig den direkte; .map/.rad versioneres ikke, kun `layout.yaml`). Alle koordinater er heltal på `grid` (standard 16). 1 unit ≈ 1 inch; en spiller er 32×32×72.

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
detail: false                 # lave solider (trapper, ramper, kasser <= 128 høje) i én func_detail (SDHLT): blokerer
                              # som world, men splitter ikke vis-leaves. Kiler og høje solider forbliver world
                              # (de lukker sigtelinjer for VIS, og CSG fjerner fladerne bag dem).
                              # ⚠️ VERIFICÉR: med fast-RAD bliver func_detail-flader mørke i vores renders
                              # (lightmap findes, style 0). Standard er derfor false.
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

### Pakke 2 (2026-10-11): former, materialer, etager, vand, lys og lyd
```yaml
cover:
  - {name: pillar, area: hall, pos: [x, y], size: [64, 64, 192], shape: octagon}   # box | octagon (afskårne hjørner)
  - {name: crate, area: b_site, pos: [x, y], size: [64, 64, 64], breakable: wood}  # wood|metal|glass|concrete → func_breakable
  - {name: lamp, area: a_site, pos: [x, y], size: [64, 64, 8], z: 176, texture: DEV_LIGHT}  # teksturlys
areas:
  - {name: loft, rect: [...], floor: 176, height: 160}   # oven på `hall` (gulv >= hallens loft + 8)
  - {name: hall, rect: [...], light: {brightness: 300, spacing: 256}, sound: 17}  # lys pr. område (off: true slukker); env_sound-rumtype
hatches:                      # lodret hul mellem et område og det ovenpå (stablede etager)
  - {name: h1, lower: hall, upper: loft, rect: [256, -64, 320, 64], ladder: +x}   # ladder: stige op gennem hullet
water:                        # væske (!WATER) fra gulvet op til depth; lavt = vade, dybt = svømme
  - {name: pool, area: b_site, rect: [x0, y0, x1, y1], depth: 24}
spots:                        # light_spot: pitch -90 = lige ned, cone = [indre, ydre] halvvinkel
  - {name: s1, area: a_site, pos: [x, y], z: 176, pitch: -90, cone: [30, 45], brightness: 300}
texlights: {DEV_LIGHT: [255, 236, 200, 900]}   # → maps/<map>/src/<map>.rad, hlrad -lights (kun brugte teksturer)
sounds: true                  # env_sound i hvert område: rumklang efter størrelse (korridor = tunnel, rum = beton,
                              # udendørs, vand); `sound:` på et område vælger selv
diagonals:                    # makro: en 45°-korridor af mindst `width` i et kvadratisk rect (område + to kiler)
  - {name: diag, rect: [512, 272, 1024, 784], width: 192, dir: ne, height: 192}   # ne: SV→NØ, nw: SØ→NV
```

### Pakke 3 (2026-10-15): runde former, kasse-presets og buer
```yaml
cover:
  - {name: drum, area: hall, pos: [x, y], size: [96, 96, 128], shape: cylinder}   # facetteret: 8/12/16 sider efter størrelse
  - {name: b_stack, area: b_site, pos: [x, y], preset: crate_stack}   # 128x64x128: to kasser + én ovenpå (boost)
  - {name: oil, area: mid, pos: [x, y], preset: barrels, breakable: metal}   # 96x96x48: tre tønder (hver sin func_breakable)
  - {name: step, area: a_site, pos: [x, y], preset: pallets}   # 64x64x16: lavt trin (<= 18, kan gås op på)
```
- `cylinder`: hjørnerne snappes til 8-gitteret og reduceres til deres konvekse hylster; min. 32 på tværs. Under 64 bliver det en ottekant, 64–127 tolv sider, ≥ 128 seksten.
- `preset`: `size` er valgfri (standardmål ovenfor) og angiver fodaftrykket; alle dele ligger inden for det, så spawns og værktøjskassen behandler presettet som én kasse. `crate_stack` lægges langs den lange side (lang side delelig med 32, højde med 16); `barrels` kræver mindst 64 på tværs (kort side delelig med 16). `shape` kan ikke kombineres med et preset. `breakable` gælder hver del (`break_<navn>_<n>`).
- Værktøjskassen: `add_cover` med `shape: cylinder` eller `preset` (uden `size`).

```yaml
doors:
  - {name: mid_a, between: [mid, a_site], width: 128, arch: true}   # bue: øverste hjørner rundes af
```
- `arch` (kun en almindelig dør: ingen `gate`, `glass`, vindue eller vent): en halv-elliptisk bue over hele bredden, stigning = halv bredde, men vederlaget ligger altid mindst 80 over gulvet, så en stående spiller (72) passer i hele bredden. Hjørnerne fyldes med trekanter i gitteret gennem væggen (world brushes). Kræver en åbning på mindst 96 i højden.
- Værktøjskassen: `set_arch` (target, `arch: false` fjerner den) og `add_connection` med `arch: true`.

```yaml
hatches:
  - {name: h_lift, lower: b_site, upper: b_upper, rect: [x0, y0, x1, y1], lift: button}   # auto | button
```
- `lift` på en lem: en `func_plat` fylder hullet i det øverste gulv (tegnet i topposition, `height` = forskellen mellem gulvene) og kører ned til det nederste gulv. `auto`: venter nede og kører op, når man træder på den. `button`: starter oppe; en `func_button` på en sokkel (16×16×40) ved siden af lemmen på hver etage sender den op/ned (soklen placeres på første ledige side +x, -x, +y, -y). Min. 64 på tværs, højst 512 i højden, udelukker `ladder`.
- **Bots kan ikke bruge elevatoren** (verificeret 2026-10-15 i YaPB's kilde: kræver `NodeFlag::Lift`-noder, som auto-analysen aldrig laver), og validatorens gangbarhedsgraf ignorerer `func_plat`. Elevatoren er derfor en ekstra rute for mennesker; etagen skal kunne nås ad anden vej (stige, trappe, rampe). Den er ikke i værktøjskassen.

### Tema-props (2026-10-15): industri
```yaml
cover:
  - {name: a_wagon, area: a_long, pos: [x, y], preset: rail_wagon}        # 384x128x144, som toget på de_train
  - {name: b_box, area: b_site, pos: [x, y], preset: container}           # 256x112x128
  - {name: ovn, area: a_site, pos: [x, y], preset: ladle}                 # 128x128x96 støbeske (cylinder)
  - {name: truck, area: mid, pos: [x, y], preset: forklift}               # 128x64x128, mast i den ene ende
  - {name: ingots, area: a_site, pos: [x, y], preset: ingot_stack}        # 128x64x48, to lag
  - {name: rør, area: b_site, pos: [x, y], preset: pipe_run, z: 160}      # 256x32x32 vandret rør (op ad en væg)
```
- Alle presets og props står i `mapforge/generator/props.py` (`PROPS`: standardmål, tema, mindstemål). Orienteringen følger fodaftrykkets lange side; `size` drejer propen (fx `[128, 384, 144]` for en vogn langs y).
- Tema-props har egne teksturer fra spillets standard-WADs (`tswad.wad`, `cs_bdog.wad`), som refereres, aldrig embeddes; generatoren skriver selv WAD'erne i `wad`-nøglen. `texture` på cover-elementet overstyrer propens teksturer.
- `rail_wagon`: to skinner (8 høje – et trin, ingen væg), bogier i enderne, et lukket undervogn imellem (intet hul at sidde fast i) og vognkassen ovenpå.
- Props kan ændre spillet, og efter Gate B er de stadig frie (kun layoutet er låst, FITNESS.md). Værktøjskassen: `add_cover` med `preset`.

### Lyd (2026-10-15)
```yaml
ambient:
  - {name: a_furnace, area: a_site, sound: ambience/industrial1.wav, volume: 6}   # radius: small|medium|large|everywhere
  - {name: b_drips, area: b_tunnels, sound: ambience/drips.wav, pos: [x, y], z: 64, radius: small}
```
- `ambient_generic` (looper); `sound` er en sti under `sound/`, som spillet selv har (`cstrike/sound` eller `valve/sound`, CS 1.6 falder tilbage på valve). Generatoren afviser stier, der ikke findes i `paths.sound_dirs` (tjekket kun når Half-Life-installationen er mountet). Standard: områdets midte, 64 over gulvet, volumen 6, radius medium.

### Skyline: bygninger i forskellige højder (2026-10-15, omlagt efter spiltest)
```yaml
skyline:                      # eller bare `skyline: true`
  heights: [0, 32, 64, 96, 160, 224]   # en bygningsbloks variation (vælges stabilt ud fra dens placering)
  air: 128                    # fri luft over det højeste tag, før himlen
  facade: BRICK05-2           # facader ud mod luften (standard: textures.wall)
  roof: TSROOF                # tagflader (standard: textures.ceiling)
```
- Uden `skyline` er skallen klassisk: massiv op til toppen, himmel kun lodret over udendørs områder.
- Med `skyline` er **gårdene gaderne**: deres kanter (og en vægtykkelse ud fra dem) skærer planen op i byblokke. En gårds egen søjle er åben over dens top, og **væggen om den** slutter 16 over (samme højde hele vejen rundt); en åbning mellem to gårde er åben opad (ingen bjælke over den). **Hver anden blok er én bygning** – høj nok til alt indendørs under den (loft + væg; et skråt loft: kip + væg) og til gårdvæggene ved siden af – plus en variation og et **saddeltag** (kip langs den lange side, rejsning halvdelen af den korte, højst 96). Så flugter bygningerne langs gårdene, og alle har tag.
- Over tagene er der åben luft op til himlen, og himlen dækker skallens yderside. Hver gård får et spiller-clip-loft i sin oprindelige top, så ingen kan booste op på tagene (granater og skud går igennem clip).
- Mere kan ses hen over tagene: hold øje med r_speeds/wpoly i valideringen.
- Version 1 (pr. område) gav smalle striber uden tag, version 2 (pr. massiv blok) stumper, der ikke flugtede – begge fundet ved spiltest 2026-10-15.

### Låste døre og vinduer langs væggene (2026-10-15)
```yaml
wall_details:
  areas: [t_spawn, mid_s, ct_spawn]
  spacing: 352                # en plads hver 352 units langs hver væg
  door_every: 3               # hver 3. plads er en dør, resten vinduer
  recess: 16                  # dør-/vinduesfladen sidder 16 inde i væggen
  frame: TSIBEAM              # valgfri: en flush indfatning (16 bred) rundt om – intet stikker ud
  doors:   [{texture: TSDOOR4, size: [64, 104], tex: [80, 128]}]
  windows: [{texture: WINDOW04A, size: [96, 48], tex: [128, 64], z: 104}]
```
- Døre og vinduer er **forsænkede** (play test 2026-10-15): en niche `recess + 8` dyb skæres kun ud, hvor væggen er massiv så dybt (plus en vægtykkelse bag ved, intet andet rum), og panelet fylder dens bund. `size` er panelets størrelse i menneskeskala; teksturen (`tex` = teksturens størrelse) skaleres, så panelet viser præcis én hel dør eller ét helt vindue. Med `frame` får nichen en flush indfatning (karme, overligger og under et vindue et bånd), så åbningen ikke stikker ud af væggen. Paneler holder 24 fri af rigtige åbninger, cover, modeller og stiger, og passer under loftet. `func_detail`. Tekstur pr. plads vælges stabilt.

### Tage og skrå lofter (2026-10-15)
```yaml
roofs:      # tag over en del af et område, åbne sider (halvtag i en gård, skur på stolper)
  - {name: a_canopy, area: a_site, rect: [x0, y0, x1, y1], z: 160, shape: gable, axis: y, rise: 48, posts: true}
  - {name: ct_shed, area: ct_spawn, rect: [...], z: 128, shape: shed, axis: x, rise: 32}   # flat | shed | gable
areas:
  - {name: b_hall, rect: [...], height: 224, pitch: {shape: gable, axis: x, rise: 64}}   # skråt loft i en hal
```
- `roofs`: `z` = tagfodens højde over gulvet (mindst 96: over hovedhøjde), `rise` = hvor meget det stiger (0 for flad), `thickness` 8, `texture` (standard: zonens loft). `gable`: kip langs `axis`; `shed`: stiger langs `axis` (lavest i den lave ende). `posts: true` sætter en 16×16-stolpe under hvert hjørne – kun stolperne står i spilrummet. Taget skal ligge inden for området og under dets loft.
- `pitch` (kun rektangulære indendørs områder): rummet beholder sin højde op til tagfoden (`height`), og taget rejser sig `rise` derover; rummet bliver højere, og prismer fylder ud over skråningerne (samme princip som buer). Generatoren afviser et skråt loft, der ville løbe op i et område ovenover. Gangbart rum er uændret.

### Dørkarme og dørlys (2026-10-15)
```yaml
doors:
  - {name: d_long_n2, between: [long_ec_n, a_site], width: 192, frame: TSIBEAM}
```
- `light: true` på en dør: et lys 48 inde i hvert af de to områder, midt for åbningen og 16 under dens overkant (eller loftet), med områdets lysfarve og -styrke. Til chokepoints, så de læses tydeligt fra begge sider.
- `frame` (tekstur): to karme og et overligger, 16 brede og 8 ud af væggen på begge sider, som `func_detail` (deler ikke VIS). Overliggeren udelades, hvor den ville nå loftet (en dør i fuld højde får kun karme). Ikke på vinduer, vents eller døre med `arch`.

### Modeller fra spillet (2026-10-15)
```yaml
models:
  - {name: a_belt, area: a_site, model: models/conveyor1.mdl, pos: [x, y], yaw: 90, clip: [64, 192, 48]}
  - {name: b_lamp, area: b_site, model: models/light.mdl, pos: [x, y], z: 200}
```
- `env_sprite` med en `.mdl`, som spillet selv har (`cstrike/models`, `valve/models`); stien skal starte med `models/`. Generatoren afviser modeller, der ikke findes i `paths.model_dirs` (når Half-Life-installationen er mountet).
- Modellen er ikke solid. `clip: [w, d, h]` lægger en CLIP-boks (spiller-clip, ses ikke) centreret om `pos` fra områdets gulv (også når `z` løfter modellens origin, fx `pallet_with_bags`: z 22), så den blokerer; uden `clip` er den ren pynt (sæt den op ad en væg eller over hovedhøjde).
- Vores renderer tegner ikke modeller, så stilreviewet ser dem ikke. ⚠️ VERIFICÉR visningen i CS 1.6-klienten.

### Vinkler og niveauer (2026-10-14): skrå rum i vilkårlig vinkel, broer, overgange
```yaml
areas:
  - name: hex                 # konveks grundplan (grid-vertices, vilkårlig rækkefølge); rect = bounding box
    poly: [[1024, 400], [1216, 272], [1408, 272], [1536, 400], [1536, 624], [1024, 624]]
    height: 192               # resten af boxen er solid (prismer); døre kun på polygon-kanter, der
                              # ligger på boxens sider (fx kanten y=272 fra x 1216 til 1408)
corridors:                    # makro: skrå korridor i vilkårlig grid-vinkel → poly-område (+ rampe + døre)
  - name: t_long
    from: [-1280, 272]        # midten af den ene ende (på grid); enderne står vinkelret på hovedaksen,
    to: [-960, 960]           # så de sidder på almindelige vægge (her y=272 og y=960)
    width: 128                # bredde målt på tværs af skråningen; enderne bliver width / cos(vinkel)
    floor: 0
    height: 192               # loftshøjde over det (skrå) gulv: med rise bliver området rise højere
    rise: 64                  # valgfri: rampe hele vejen fra from til to (negativ = nedad); <= længde/2
    via: [[-1120, 640]]       # valgfri: knæk; hvert punkt bliver et lille kvadratisk knæ-rum (<name>_knee1 …),
                              # stykkerne <name>, <name>_2 …; rise fordeles efter længde; bryder lange sigtelinjer
    between: [t_spawn, a_site]  # valgfri: døre <name>_from / <name>_to i hele endens bredde (door_width);
                              # floor og rise udelades så normalt: de følger de to områders gulve
bridges:                      # gangbart dæk tværs over et højt område, væg til væg langs axis
  - {name: deck, area: street, axis: y, z: 176, width: 128, pos: 0, thickness: 16, rail: 40}
                              # z = dækkets top over gulvet; >= 80 fri under (z - thickness) og over;
                              # rail = rækværk i begge sider (0 = intet); lys under dækket sættes selv
```
- **Layout-grafen** (validatorens site-indgange/kryds): en dør i dækhøjde fører ind på broen, ikke ned i rummet under den; broen er sit eget niveau.
- **Cover og spawns:** et covers hjørner skal ligge på 8-gitteret, og spawns springer pladser over, hvor de ville stå i (eller tættere end 16 units på) cover.
- **Polygon-områder:** spawns, lys, cover og stiger skal ligge på polygonens gulv (spawns/lys filtreres, cover og stiger giver fejl). En `poly` der er et akse-rettet rektangel, bliver et almindeligt område.
- **Overgange:** et område må ligge oven over et andet (forskellig `floor`, ingen overlap i højden), også over et udendørs område: skallen omkring det (gulvplade, sidevægge og tag, hvis det ikke selv er udendørs) bliver solid i stedet for himmel, så en overdækket gangbro kan krydse en åben gade.
- **Broer i det fri:** et højt udendørs område med `bridges:` og rum på begge sider i dækhøjde (døre fra rummene ender på dækket) giver to niveauer i samme rum: man ser og skyder mellem dem.
- **Skitser:** `./mf sketch MAP=<map>` gør streger tegnet på dashboardet (path-annotationer) til layout-YAML: stregen forenkles (Ramer–Douglas–Peucker, `--tolerance`) til knæk på gitteret, hvert knæk bliver et lille kvadratisk rum (`s<id>_knee<i>`), hvert stykke en `corridors:`-post (`s<id>_<k>`) med døre ind i knæene. Stregens ender står åbne: de forbindes til de områder, den er tegnet fra og til. Stykker tæt på 45° afvises (brug `diagonals:`).
- Decide: `bend_corridor` (`target`, `via`: knæk en skrå korridor, `[]` retter den ud igen), `add_bridge` (`zone`, `axis`, `z`, valgfri `width`/`pos`/`rail`), `remove_element` fjerner en bro; `move_corridor` flytter også polygon-områder og skrå korridorer (begge ender), `resize_corridor` afviser skrå områder.

**Dev-WAD:** ud over grundsættet har `mapforge_dev.wad` tool-teksturerne `CLIP` og `ORIGIN`, entitetsteksturerne `DEV_GLASS`, `DEV_DOOR` og `DEV_LADDER`, zone-tints `DEV_{FLOOR,WALL,CEIL}_{RED,BLUE,GREEN,SAND,GREY}` og landmark-materialerne `DEV_METAL`, `DEV_BRICK`, `DEV_CONCRETE` og `DEV_WOOD`. Fra pakke 2 også `DEV_LIGHT`, `DEV_LIGHT_BLUE` (teksturlys) og `!WATER`. Alt er proceduralt og vores eget arbejde (CC0).

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

Navne i `landmarks[].element`, `irregularities[].element` og `chokes[].door` er låst: `apply.py` afviser at flytte, fjerne eller ændre dem (som `protected`). Én undtagelse: `bend_corridor` (knæk ind eller ud igen) på en skrå korridor, der *kun* er en irregularity, er tilladt – den forbliver en skrå korridor (besluttet 2026-10-15).

## Beskyttede elementer
`protected: true` på et område, en dør eller et cover betyder, at loopet aldrig flytter, ændrer størrelse på eller fjerner det (låst topologi, fx chokepoint-dørene i de_forge01). Områder med `role: site`, `t_spawn` eller `ct_spawn` er altid låste (site-placeringer, FITNESS).

## Hvad Decide kan ændre (fase 6)
Værktøjskassen i `config/fitness.yaml` peger på navne i spec'en: `move_corridor`/`resize_corridor` → et områdes `rect`; `adjust_opening` → en dørs `width`/`height`; `add_cover`/`remove_cover` → `cover`; `move_spawn` → spawn-område; `add_connection`/`remove_connection` → `doors`; `remove_area` (kun på et menneskes annotation) → fjerner et område med dets døre, cover og trapper. Fra 2026-10-11 også: `add_cover` med `z`/`texture`; `add_connection` med `kind: vent`; `add_window` → en dør med `kind: window`; `set_gate` → en dørs `gate`; `add_ramp` → `ramps`; `add_wedge` → `wedges`; `add_ladder` → `ladders`; `remove_element` → fjerner en rampe, kile, stige, cover, trappe eller et vindue ved navn. `add_area` må ligge over/under et andet område (adskilt i højden). Pakke 2: `add_cover` med `shape`/`breakable`, `set_breakable`, `add_hatch` → `hatches`, `add_water` → `water`. Derfor skal alle navne være unikke. Ændringerne anvendes af `mapforge/loop/apply.py` med round-trip-YAML (kommentarer bevares); hver ændring prøve-genereres, og en ændring, der ikke kan bygges (fx en dør mister sin fælles væg), springes over med begrundelse.
