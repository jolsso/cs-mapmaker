# Mapmaker – simpel og avanceret input (Fase 8)

Fra en idé til et spilbart, tema-klædt de_-map. To modes:

- **Simpel:** beskriv banen i ord + vælg et antal billeder som tema.
- **Avanceret:** samme som simpel + tegn banen op i lag (niveauer, detaljer, assets, intentioner).

Alt efter input genbruger den eksisterende pipeline (generate → compile → validate → render → review → simulate → analyze → decide → loop). Fase 8 bygger kun det, der mangler *før* `layout.yaml` findes, og tema-laget bagefter.

## Princip: skitsen er det fælles mellemled

Begge modes ender i den samme fil: `maps/<map>/sketch.json`. I avanceret mode tegner mennesket den. I simpel mode tegner agenter den (flere kandidater). Alt derefter er fælles og deterministisk:

```
 SIMPEL                          AVANCERET
 brief + billeder                brief + billeder + tegning (lag)
        │                                │
        ▼                                ▼
 ┌─────────────┐                  ┌─────────────┐
 │ Interpreter │ agent            │ Interpreter │ agent (læser også tegningen)
 └──────┬──────┘                  └──────┬──────┘
        ▼  intent.json  ◀── 🚦 "sådan har jeg forstået dig" ──▶  intent.json
 ┌─────────────┐                         │
 │  Sketcher   │ agent + MAP-Elites      │ (menneskets sketch.json,
 │ K kandidater│                         │  evt. suppleret af Sketcher)
 └──────┬──────┘                         │
        └──────────────┬─────────────────┘
                       ▼  sketch.json (pr. kandidat)
              ┌─────────────────┐
              │ Parse → Fit     │ kode: topologi, skala, regler vs. troskab
              └────────┬────────┘
                       ▼  layout.yaml + fit_report.json
              ┌─────────────────┐
              │ build → validate│ eksisterende hurtigt loop
              │ → render→review │
              └────────┬────────┘
                       ▼
              🚦 Gate A: kandidatgalleri – mennesket vælger
                       ▼
              eksisterende loop (simulate → analyze → decide)  →  🚦 Gate B
                       ▼
              ┌─────────────────┐
              │ Dresser         │ agent + kode: tema, materialer, prefabs, lys
              └────────┬────────┘
                       ▼
              Brief-troskab (agent)  →  🚦 Gate C
```

Hvorfor skitsen som mellemled: den sværeste del af fri generering er *indlejringen* (hvor ligger rummene i 2D/2.5D?). En skitse leverer den. Simpel mode bliver derfor "agenter tegner en skitse" i stedet for et separat system, og begge modes forbedres, hver gang Parse/Fit forbedres.

Samme regel som Review og Decide i dag: **agenter beslutter intention, kode beslutter geometri og pass/fail.** Hver agent får en prompt-fil og et JSON-skema, en frisk subagent skriver svaret, og `--answer` validerer det i koden.

## De to modes

| | Simpel | Avanceret |
|---|---|---|
| Menneskets input | brief (felter + fritekst), 3–12 tema-billeder | det samme + tegning i lag |
| Hvem laver `sketch.json` | Sketcher (K = 6–10 kandidater) | mennesket (Sketcher kan foreslå manglende lag) |
| Fit-troskab | lav–middel (skitsen er agentens gæt) | høj som standard, skyder 0,3–0,95 |
| Menneske-gates | intent, Gate A (vælg kandidat), B, C | intent, Gate A (vælg fit-variant), B, C |
| Tid til første spilbare blockout | ~30 min ubemandet | ~10 min efter tegningen er færdig |

## Input-formater

### `maps/<map>/brief.json` (v2)
Udvider den eksisterende `brief.json` (dashboardets `POST /api/maps`). Felterne svarer til sjæl-sektionen i LAYOUT_SPEC, så Interpreter ikke skal opfinde noget nyt. Alle felter undtagen `name` og `description` er valgfrie; tomme felter udfylder Interpreter og viser dem til bekræftelse.

```json
{
  "version": 2,
  "name": "de_ferry",
  "mode": "simple",
  "description": "Forladt færgehavn om vinteren. A er kajen, B er inde i terminalen.",
  "concept": "Bomben skal ødelægge færgelejet, før det sidste skib lægger til",
  "archetype": "asymmetric",
  "pace": "medium",
  "sightlines": {"long": "few", "cqb": "many"},
  "sites": {
    "A": "åben kaj, lang sigtelinje fra CT, svær at tage uden smokes",
    "B": "to etager inde i terminalen, tæt og vertikal, let at tage, svær at holde"
  },
  "mid": "en beslutning: kontrol over mid åbner en tredje vej til B",
  "must_have": ["kran som landmark ved A", "lem fra terminalens 1. sal ned til B"],
  "no_go": ["ingen lange lige korridorer fra spawn"],
  "size": "medium",
  "created": "2026-10-15 14:00",
  "status": "brief"
}
```

`archetype`: et af de data-drevne arketype-navne (8d: klynger af referencemaps' topologier); indtil da `three_lane` | `asymmetric` | `stacked`. `pace`: `fast` | `medium` | `slow`. `size`: `small` | `medium` | `large` (styrer skala-målet i Fit). `sightlines` bruges direkte som mål for adfærdsdimensionerne i MAP-Elites (8d).

### Billeder: `maps/<map>/brief/images.json`
Hvert billede får et **tag**, så pipelinen ved, hvilket lag det styrer:

| Tag | Styrer | Bruges af | Fase |
|---|---|---|---|
| `mood` | stemning, palet, lys, årstid | Interpreter, Dresser | tidligt (intent) og art pass |
| `landmark` | et konkret element, der bygges og låses | Interpreter, Sketcher, Dresser | tidligt (påvirker layout) |
| `material` | overflader (beton, rust, træ) | Dresser | art pass |
| `layout` | plantegning, luftfoto, papirskitse | Interpreter → forslag til `sketch.json` | tidligt |

```json
[
  {"file": "kran.jpg", "tag": "landmark", "note": "kranen skal kunne ses fra A main", "license": "own"},
  {"file": "havn_tåge.jpg", "tag": "mood", "note": "", "license": "inspiration"},
  {"file": "rust_plade.jpg", "tag": "material", "note": "til containerne", "license": "own"}
]
```

**Licens-regel** (forlænger reglen for referencemaps): `license: inspiration` = billeder fra nettet o.l. De ligger kun lokalt (`brief/inspiration/`, gitignored), må læses af agenter og aldrig blive til teksturer. `own` og `cc0` må committes og kan blive til WAD-teksturer (fase 7's billede → WAD3-pipeline). Upload stripper EXIF. Kun PNG/JPEG, maks. ~8 MB pr. billede.

### `maps/<map>/sketch.json` (lag-tegning)
Forskellig fra `annotations.json`: annotationer er ønsker på et map, der *findes*; skitsen er input, *før* layoutet findes. Koordinater i verdensunits på dashboardets tomme gitter (±3072 som i dag).

```json
{
  "version": 1,
  "scale_hint": null,
  "levels": [
    {"id": "cellar", "name": "Kælder", "floor": -192},
    {"id": "street", "name": "Gade",   "floor": 0},
    {"id": "upper",  "name": "1. sal", "floor": 160}
  ],
  "layers": {
    "structure": [
      {"id": "s1", "kind": "area", "role": "site", "site": "B", "level": "street",
       "points": [[-2400, 600], [-1500, 600], [-1500, 1800], [-2400, 1800]], "lock": "fixed",
       "text": "terminalhallen"},
      {"id": "s2", "kind": "stroke", "role": "corridor", "level": "street",
       "points": [[-200, -900], [-900, -300], [-1500, 900]], "width": "normal", "lock": "flexible"}
    ],
    "connectors": [
      {"id": "c1", "kind": "hatch", "from": "upper", "to": "street", "at": [-2000, 1500], "ladder": true},
      {"id": "c2", "kind": "ramp",  "from": "cellar", "to": "street", "points": [[-1900, -800], [-1900, 400]]}
    ],
    "details": [
      {"id": "d1", "kind": "prefab", "prefab": "container", "level": "street", "at": [1800, 1200], "rot": 90},
      {"id": "d2", "kind": "window", "between": ["s2", "s1"], "at": [-1500, 900]},
      {"id": "d3", "kind": "cover",  "level": "street", "at": [-2100, 1100], "size": "low"}
    ],
    "intent": [
      {"id": "i1", "kind": "sightline", "points": [[1500, -400], [1900, 1600]], "text": "AWP-linje ned ad kajen"},
      {"id": "i2", "kind": "choke", "at": [-1500, 900], "text": "B-døren, flash-spot"},
      {"id": "i3", "kind": "landmark", "at": [2000, 1500], "image": "kran.jpg"}
    ]
  }
}
```

**Lås pr. element:** `fixed` (Fit må ikke flytte eller ændre det), `flexible` (må justeres, koster troskab), `hint` (kun en idé; må ignoreres med begrundelse). Standard: sites, spawns og landmarks = `fixed`, alt andet = `flexible`.

**Lag i editoren:** *Struktur* (områder og streger pr. niveau; andre niveauer vises dæmpet nedenunder), *Forbindelser* (lem, stige, rampe, trappe, drop – altid mellem to niveauer), *Detaljer* (cover, vinduer, døre, vand, lys, prefabs), *Intention* (sigtelinjer, chokes, landmarks med billede, fritekst). Hvert lag kan skjules.

## Agenter og trin

| Trin | Type | Input | Output | Validering i kode |
|---|---|---|---|---|
| **Interpreter** | agent | brief.json, billeder, evt. sketch.json | `intent.json`: concept, archetype, site-karakter, landmarks, mål for timings/sigtelinjer/størrelse, tema-tags, palet, åbne spørgsmål | skema; hvert `must_have` dækket eller begrundet afvist |
| 🚦 **Intent** | menneske | intent.json på dashboardet | bekræftet/rettet intent | – |
| **Sketcher** | agent + kode | intent.json, arketype-skabeloner, MAP-Elites-arkiv | K × `candidates/<k>/sketch.json` | skema; K kandidater skal være forskellige (topologi-afstand) |
| **Parse** | kode | sketch.json | `topology.yaml` + rå `layout.yaml` | deterministisk; fejler med position ved tvetydige kryds |
| **Fit** | kode | rå layout, topologi, intent, `fidelity` | `layout.yaml`, `fit_report.json`, overlay-render | faste elementer urørt; alle ændringer listet med årsag |
| build → review | kode + agent | eksisterende | eksisterende | eksisterende |
| **Curator** | agent | alle kandidaters renders, validation, design_stats, fit_report | galleritekst: "hvorfor denne", styrker/svagheder, callout-navne | skema |
| 🚦 **Gate A** | menneske | galleri | valgt kandidat (+ evt. "remix"-ønsker) | – |
| **Dresser** | agent + kode | intent, billeder, valgt layout | zoner, materialer, prefabs, lys, `ART_DIRECTION.md` | samme tilladte-ændringer-politik som Decide; ingen geometri efter Gate B |
| **Brief-troskab** | agent | brief, intent, endelige renders | score 1–5 pr. brief-punkt + fund | skema; diagnostik, ikke i fitness-vægten |

Alle agenter følger mønstret fra Review/Decide: `./mf <trin> MAP=… ` skriver `…_prompt.md` + skema → frisk subagent → `./mf <trin> MAP=… -- --answer`. Ubemandet: `--headless` (`claude -p`).

## Parse

- Områder (polygon/rect) → `areas` på deres niveaus `floor`; ikke-akse-rettede polygoner → `poly` (findes).
- Streger → `corridors:`-makro via `mapforge/sketch.py` (findes; udvides med niveau og bredde-klasse `narrow|normal|wide` = 64/128/192).
- Hvor en streg eller et område rører et andet på samme niveau (inden for en tolerance, fx 96 units) → dør. Rører den to ting tæt på hinanden → tvetydigt kryds: Parse gætter og markerer det i `parse_report.json`, som dashboardet viser *før* Fit.
- Forbindelser → `hatches`, `stairs`, ramper, `func_ladder` (findes i generatoren).
- Detaljer → `cover`, vinduer, `water`, lys, prefabs (se Tema og assets).
- `topology.yaml` udtrækkes af `layout_graph()` udvidet til at returnere hele grafen (noder: rolle, niveau, størrelse; kanter: door/window/vent/hatch/ladder/ramp + længde).

## Fit

Mål: mindst mulig afvigelse fra skitsen, så designreglerne er opfyldt.

```
minimér   Σ regelstraf(layout)  +  λ(fidelity) · Σ afvigelse(element)
hvor      faste elementer er hårde constraints, alt snappes til grid 16 til sidst
```

1. **Global skala først.** Én faktor (pr. akse tilladt inden for ±15 %), så T → sites rammer timing-båndet for `size`. Løser typisk halvdelen af timing-problemerne uden at forvrænge formen.
2. **Lokal tilpasning:** positioner, korridorlængder og -knæk, bredder, dørplaceringer, niveau-højder. Simulated annealing eller CMA-ES på graf-niveau-evaluatoren (8b), ms pr. evaluering.
3. **Regelstraf** = design-reglerne fra DESIGN_GUIDE §2 og §9 (timings, CT ≥ 3 s før T, rotation, 2–3 site-indgange med CT-retake, ingen 4-vejskryds, spawn-sigtelinjer) + mål fra intent (sigtelinje-fordeling, størrelse).
4. **Afvigelse** = flytning af noder, ændret længde, ændret vinkel, ændret bredde – vægtet efter lås (`flexible` 1, `hint` 0,2).
5. **Topologiændringer laves aldrig af Fit.** Kan reglerne kun opfyldes ved at tilføje/fjerne en forbindelse, skriver Fit et forslag i `fit_report.json` (som Decide's eskalering).
6. **Verifikation:** de bedste varianter går gennem compile + walk + `design_stats` (BSP-niveau). Afviger BSP-tallene fra graf-estimatet ud over tolerancen, logges det til kalibreringen af evaluatoren.

**Varianter:** Fit kører med `fidelity` 0,9 / 0,6 / 0,3 og giver tre layouts. Galleriet viser dem med skitsen lagt ovenpå og en ændringsliste: *"B-tunnel forlænget 320 u: T nåede B på 11 s (mål 14–26)"*.

## Graf-laget

Hvordan modellerne trænes (datasæt, tensorer, arkitekturer, træningsløkker, evaluering, infrastruktur): `docs/GRAPH_TRAINING.md`.

Grafen er mapmakerens rygrad: skitser, layouts, referencemaps og genererede kandidater oversættes alle til den samme topologi, og al søgning, læring og diversitet foregår på den. Geometri kommer først bagefter (Parse/Fit).

### `topology.yaml`
Motor-neutral (forberedelse til CS2). Udtrækkes fra ethvert `layout.yaml` (`layout_graph()` udvidet), fra `sketch.json` (Parse) og fra en BSP (8g).

```yaml
version: 1
source: generated            # layout | sketch | refmap | generated
nodes:
  - {id: t_spawn, role: t_spawn, level: 0, size: L}
  - {id: mid,     role: mid,     level: 0, size: M}
  - {id: b_choke, role: choke,   level: 0, size: S}
  - {id: b_site,  role: site, site: B, level: -1, size: L}
  - {id: b_upper, role: room,    level: 1, size: M}
edges:
  - {a: t_spawn, b: mid,     kind: door,  length: 1400, width: normal}
  - {a: mid,     b: b_choke, kind: door,  length: 900,  width: narrow, choke: B-døren}
  - {a: b_choke, b: b_site,  kind: ramp,  length: 600}
  - {a: b_upper, b: b_site,  kind: hatch, length: 64}
  - {a: b_upper, b: b_site,  kind: drop,  oneway: true}
  - {a: mid,     b: b_upper, kind: window}          # sigtelinje, ikke gangbar
pos: {t_spawn: [0, -2300], b_site: [-2000, 1200]}   # valgfri grov indlejring
```

- **Roller:** `t_spawn`, `ct_spawn`, `site`, `mid`, `choke`, `corridor`, `room`, `connector`. **Størrelse:** `S|M|L|XL`. **Kanter:** `door`, `vent`, `ramp`, `stairs`, `ladder`, `hatch`, `drop` (envejs), `window` (kun sigtelinje). `length` = rutelængde i units (det, Fit sigter efter). `choke` = navnet fra layoutets `chokes:`, når forbindelsen selv er et chokepoint – udtræk fra et layout giver chokes som kant-egenskab, mens Parse/generatoren kan bruge rollen `choke` på en node.
- **Invarianter** (hårde, tjekkes af kode før alt andet): præcis én T-spawn, én CT-spawn, to sites; sammenhængende; begge sites nåbare fra begge spawns (envejskanter respekteret); ingen kant spawn ↔ site; 2–3 site-indgange inkl. en CT-retake-vej; ingen 4-vejskryds (DESIGN_GUIDE §9); grad ≤ 4; **plan graf pr. niveau** (`networkx.check_planarity`) – en ikke-plan graf kan kun lægges ud med broer/niveauer og afvises eller markeres til Fit.

### Operatorer
Al ændring af en topologi sker gennem et lille sæt operatorer, så MAP-Elites, Claude og remix taler samme sprog, og invarianterne tjekkes efter hver operation:

| Operator | Effekt |
|---|---|
| `split_edge` | indsæt choke/rum/knæk på en rute |
| `merge_nodes` | to rum bliver ét (L-rum) |
| `add_edge` / `remove_edge` | ny/fjernet forbindelse (afvises, hvis invarianterne brydes) |
| `reroute` | flyt en kants ende til en nabo |
| `set_kind` | door ↔ vent ↔ window, ramp ↔ stairs ↔ ladder |
| `set_level` | flyt et rum (og dets kanter) op/ned et niveau |
| `stretch` | ændr `length` inden for ±30 % |
| `graft` (crossover) | udskift et sites delgraf (site + naboer inden for 1 hop) med den tilsvarende fra en anden kandidat – grundlaget for galleriets *remix* |

**Claude som operator:** Sketcher får en kandidat og et mål ("gør mid til en beslutning") og svarer med en liste af operatorer + parametre (skema), ikke med en ny graf. Koden anvender dem og tjekker invarianterne – samme mønster som Decide → apply.

### Afstand, dubletter og nyhed
- **Dubletter:** Weisfeiler-Lehman-hash med roller som labels (ms) – identiske topologier tæller én gang.
- **Afstand:** rolle-bevidst graf-edit-distance (approksimeret; `networkx.optimize_graph_edit_distance` med lav tidsgrænse). Bruges til galleriets diversitet (8d) og til **nyhedskravet**: en genereret topologi skal have afstand ≥ τ til alle referencemaps (8g), så mapmakeren aldrig gengiver et eksisterende map.

### Graf-niveau-evaluator (8b)
Korteste veje på dør-grafen med rect-geometri (dørcentre, string-pulling tilnærmet), 250 u/s, faldtider, stiger. Leverer timings, rotation, indgange, kryds, kompleksitet C og et groft sigtelinje-estimat; kalibreres mod BSP-walk på egne maps og loop-historikken. Er der ingen `pos`, bruges `length` direkte.

**Live graf-lint i editoren (8c):** evaluatoren er hurtig nok til at køre, mens man tegner. Dashboardet viser topologien ved siden af tegningen med T/CT-timings pr. site, rotation og regelbrud ("B har kun én indgang", "4-vejskryds ved mid") og opdateres efter hvert streg.

### Søgning: MAP-Elites (8d)
Genom = topologi. Adfærdsdimensioner: arketype × kompleksitet C × andel lange sigtelinjer × CT-territorium. Fitness = graf-niveau-regelstraf + forventet Fit-stræk (fra surrogaten, når den findes) – aldrig bot-metrikker. Mutationer = operatorerne ovenfor (tilfældige + Claude). Arkivet (`build/topologies/archive/`) gemmer hver evalueret topologi med alle labels; det er generatorens træningsdata i 8g.

### Datasæt (8g)
| Kilde | Antal (skøn) | Labels |
|---|---|---|
| Egne maps + alle loop-versioner | 10–100 | graf + BSP-niveau, review, bot-diagnostik |
| MAP-Elites-arkiv | 10³–10⁵ | graf-niveau; BSP-niveau for dem, der blev compilet |
| Referencemaps, **tier A** (15 officielle) | 15 | BSP-niveau, bot-baseline; kun test og kalibrering |
| Referencemaps, **tier B** (community, ~85 i dag) | 10²–10³ | BSP-niveau, bot-baseline; realisme, arketyper, finetuning |
| Menneskelige valg (Gate A-valg, Gate C-skemaer) | få, men værdifulde | præferencepar ("A frem for B") |

**BSP → topologi** for referencemaps (bygges i 8b): segmentér walk-grafen (`mapforge/validate/walk.py`) i regioner – klyng celler og skær ved smalle passager (choke = minimum-snit mellem to store regioner), sites fra `func_bomb_target`, spawns fra entities, niveauer fra gulvhøjde, envejskanter fra fald. Kalibreres mod topologier annoteret i hånden på alle 15 tier A-maps + 5–10 tier B. Referencedata ligger i `build/` (gitignored) som alle andre referencemap-afledte filer.

### Surrogat-kritiker (8g)
Lille GNN (GINE/GATv2 i PyTorch Geometric, ensemble af 5) fra topologi → BSP-niveau-metrikker (timings, rotation, territorium, sigtelinje-fordeling) + **indlejrbarhed** (forventet Fit-stræk, sandsynlighed for at Fit lykkes). Bruges som forfilter i MAP-Elites, før Fit og compile. Ensemble-uenighed = usikkerhed → de mest usikre kandidater sendes gennem BSP-niveauet (active learning) og bliver nye labels. Forudsiger **ikke** bot-winrate (FITNESS: bots er sanity-bånd).

### Lært graf-generator (8g)
Autoregressiv transformer (få mio. parametre) over topologien serialiseret som tokens (`NODE site B L -1`, `EDGE 3 7 door 900 normal` …), betinget på intent (arketype, størrelse, tempo, sigtelinjer). Invarianter håndhæves under dekodning ved at maskere ugyldige tokens.

1. **Prætræning** på MAP-Elites-arkivet (rigeligt, alt gyldigt).
2. **Finetuning** på egne maps + referencemaps (realisme), med A/B-ombytning som augmentering.
3. **Expert iteration:** generér → filtrér (invarianter, nyhedskrav) → scor (evaluator + surrogat) → finetun på top-k; diversitetsstraf og en fast andel originaldata pr. runde mod mode-kollaps.
4. Senere: **præferencemodel** fra Gate A-valg og Gate C-skemaer som ekstra reward – den eneste kilde, der måler "sjovt".

Generatoren bliver én af Sketchers kilder ved siden af skabeloner og MAP-Elites; den erstatter dem ikke. Den er kun det værd, hvis den slår MAP-Elites på kvalitet pr. compute – det er accept-kriteriet.

### Referencemaps: tiers og arketyper
**Tiers:** A = de 15 officielle de_-maps (navneliste i config, ikke mappeplacering), B = community-maps; override pr. map. Tier A sætter designreglernes bånd og er altid test-data; tier B giver bredde. Tier er en *vægt*, ikke en dom: også officielle maps varierer i kvalitet, og nogle community-maps er bedre end flere officielle – derfor kan en tier overstyres.

**Data-drevne arketyper (8d):** referencemaps' topologier klynges; klyngerne erstatter de håndlavede arketyper, og medoiden (helst tier A) bliver skabelon for simpel mode.

### Hvor grafen indgår i de to modes
- **Simpel:** Sketcher henter topologier fra skabeloner, MAP-Elites og (efter 8g) generatoren → skabelon-indlejring giver `pos` → `sketch.json` → Parse/Fit.
- **Avanceret:** din tegning → topologi (Parse) → live graf-lint mens du tegner → Fit bruger evaluatoren; Sketcher kan foreslå topologiændringer som operatorer, du accepterer eller afviser.

## Tema og assets

GoldSrc har ingen `prop_static`. Detaljer bygges derfor primært af **brushes**:

- **Prefab-bibliotek** (`mapforge/generator/prefabs/`): parametriske brush-makroer, egen kode, CC0. Findes allerede fra fase 6b (LAYOUT_SPEC → Pakke 3): cover-presets `crate_stack`, `barrels` og `pallets`, runde søjler (`shape: cylinder`/`octagon`) og `arch` på døre. Nye: `container`, `railing`/`fence`, `pipe_run`, `crane` (landmark), `market_stall`, `car_wreck` (grov). Hver prefab har tema-tags (`harbor`, `industrial`, `desert` …), et `func_detail`-flag og et wpoly-estimat.
- **Tema → zoner:** Dresser vælger materiale og lysfarve pr. zone ud fra `mood`/`material`-billeder og tema-tags; palet udtrækkes fra billederne (k-means) og bruges til procedurelle CC0-teksturer i samme stil som dev-WAD'en.
- **Egne billeder → teksturer:** `own`/`cc0`-billeder kvantiseres til WAD3 (fase 7's tekstur-pipeline: 8-bit palet, multipla af 16, tileable crop). Licens noteres automatisk i `assets/LICENSES.md`.
- **Modeller:** kun modeller, der følger med spillet, kan refereres uden at blive distribueret (`cycler_sprite`/`env_sprite`) ⚠️ VERIFICÉR hvilke entities og stier CS 1.6 accepterer, og at de vises uden download. Egne `.mdl` er udenfor scope.
- **Budget:** prefabs tæller i r_speeds/wpoly; Dresser skal holde < ~800 wpoly pr. kameraview (FITNESS). Over budget → færre prefabs, ikke færre landmarks.
- **Radar/overview:** generér `overviews/<map>.bmp` + `.txt` fra top-down-renderen med callout-navne ⚠️ VERIFICÉR format og placering i CS 1.6.

## Dashboard

"+ Nyt map" udvides til en guide:

1. **Mode:** simpel / avanceret.
2. **Beskrivelse:** felterne fra brief v2 som formular (vejledende eksempler i felterne) + fritekst.
3. **Billeder:** træk ind, vælg tag og licens pr. billede, valgfri note.
4. **Tegning** (kun avanceret): lag-faner, niveau-vælger, værktøjer pr. lag, lås pr. element, fortryd.
5. **"Sådan har jeg forstået dig":** intent.json vist som en læsbar side + åbne spørgsmål; ret direkte.
6. **Galleri:** kandidater (simpel) eller fit-varianter (avanceret) med radar, nøgletal, Curators "hvorfor", skitse-overlay, ændringsliste, knap til `--watch`-server.
7. **Vælg / remix:** "kandidat 2, men B fra kandidat 4" → nyt Sketcher-kald med begge som input.

API (live-containeren, kun dashboardets origin som i dag): `POST /api/maps` (v2-felter), `POST /api/maps/<map>/images` (upload + tag + licens), `PUT /api/maps/<map>/sketch`, `PUT /api/maps/<map>/intent` (rettelser), `POST /api/maps/<map>/pick` (valg fra galleriet).

## Kommandoer (forslag)

```bash
./mf brief MAP=<navn>                     # Interpreter-prompt → build/<map>/intent_prompt.md
./mf brief MAP=<navn> -- --answer         # valider → maps/<map>/intent.json
./mf sketch MAP=<navn> -- --candidates 8  # Sketcher (simpel): candidates/<k>/sketch.json
./mf parse MAP=<navn> [CANDIDATE=k]       # sketch.json → topology.yaml + rå layout + parse_report.json
./mf fit MAP=<navn> [FIDELITY=0.6]        # → layout.yaml + fit_report.json (+ varianter med -- --variants)
./mf topology MAP=<navn>                  # topologi: udtræk (findes); invariant-tjek, evaluator-tal, WL-hash kommer i 8b
./mf elites -- --budget 2000              # MAP-Elites over topologier → build/topologies/archive/
./mf refgraphs                            # referencemaps (BSP) → topologier (8g)
./mf train surrogate|generator            # 8g
./mf candidates MAP=<navn>                # build → validate → render → review for alle kandidater, galleri på sitet
./mf pick MAP=<navn> CANDIDATE=k          # kopiér valgt layout til maps/<map>/, lås sites/landmarks, start loopet
./mf dress MAP=<navn>                     # Dresser-prompt; -- --answer anvender tema (efter Gate B)
./mf fidelity MAP=<navn>                  # brief-troskab-review
```

`./mf sketch` findes allerede (streger → korridorer); den udvides, så den gamle brug stadig virker (`--id`).

## Risici og åbne spørgsmål

- **Indlejring i simpel mode** kan give topologier, der ikke kan lægges ud uden urealistiske korridorer. Fit-straffen og "stræk" skal tælle i MAP-Elites-fitness.
- **Ensartethed:** agenter + regler trækker mod det samme gennemsnits-map. Modvægt: arketyper, MAP-Elites-diversitet, `irregularities` fra intent låses, brief-troskab måler "identitet".
- **Goodhart** (FITNESS): faldende troskab mod skitsen for at ramme bot-tal er et rødt flag; Fit må aldrig optimere på bot-metrikker.
- **Tvetydige skitser:** Parse skal hellere spørge end gætte stille.
- **Prefabs vs. r_speeds:** et detaljeret tema kan sprænge budgettet; måles pr. kameraview.
- Åbent: skal papirskitser (foto med tag `layout`) kunne blive en `sketch.json` automatisk, eller kun et forslag mennesket retter?
