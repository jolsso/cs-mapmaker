# Art Direction – de_nasa

Theme from the human's brief (2026-10-16): **rocket launch site**. Geometry is frozen since Gate B (2026-10-18), so the art pass changes only textures, light, sky/sun, texlights, decals, sound and decoration with no effect on walkability or sight lines. Names in brackets are areas and cover in `layout.yaml`.

## 1. World bible
- **Map name:** de_nasa ("The Launch Site")
- **Setting:** A coastal launch site on a clear, sunny morning. The rocket stands on the pad, fuelled, beside its lattice tower. Its payload, a new spy satellite, is still being checked in the clean-room lab next to the control centre.
- **Story in one sentence:** T must stop the launch, either by hitting the rocket on the open pad (A) or by hitting the satellite in the lab (B) before it is mounted.
- **What does the environment tell?** A working launch day: the pad swept clean, blast walls with warning stripes, a rocket stage parked on its transporter in the hangar, shipping containers in the yard, lab racks humming, the control centre watching the lab through its window.
- **References/mood:** the human's inspiration images (white and grey NASA buildings, a Saturn V on its pad, a stage transported sideways). Look only; nothing copied into the repo.

## 2. Zones
| Zone | Function | Story | Palette | Light mood | Landmark |
|---|---|---|---|---|---|
| T spawn (`t`: `t_spawn`, `t_to_long`, `a_long_start`, tunnels) | Service entrance + cable tunnels | Trucks and maintenance come in here | Dark asphalt, plain cool grey concrete, grey steel panels | Neutral sun outside, near-neutral white tunnels | The tunnel S-bend (`tun_wall_1/2`) |
| CT spawn (`ct`: `ct_spawn`, `ct_to_a`, `ct_to_b` with its own light 320) | Admin court by the control centre | Staff car park and walkway | Grey pavers, light cool wall panels | Cool, even | The steps up to control (`ct_b_steps`) |
| Mid (`mid`: `mid_s`, `mid`, `hangar`) | Yard between the hangars | Logistics: containers and the stage | Grey concrete, blue-grey steel-plate hangar walls, blue containers | Neutral daylight | The stage (`mid_stage`) |
| A site (`a`: `a_site`, long, short) | The launch pad outdoors | The rocket is ready to fly | Light plain concrete pad, cool grey cast-concrete walls, cool grey crates, light steel tower, white rocket | **Bright sun**, hard shadows | The tower and the rocket (`a_tower`, `a_rocket`) |
| B site (`b`: `b_site`, `b_control`) | Clean-room lab indoors | The satellite on its test stand | White tile, white wall panels, luminous ceiling | **Bright, cool white**, shadow-free | The satellite (`b_sat`) |
| B service (`bt`: `mid_to_b`, `b_doors`, `b_tunnel_n`, `b_airlock`) | Corridors and airlock into the lab | Technical corridors | Green-grey lab panels and floor | Cool, bright | The airlock (`b_airlock`) |

**Rule:** each site and each main route has one unique, recognisable landmark (callout-friendly).

## 3. Callouts
| Name | Zone | Why recognisable |
|---|---|---|
| Tower | `a_site` (`a_tower`, legs, `a_step_*`) | The steel tower on the pad; its deck is A's high spot |
| Rocket | `a_site` (`a_rocket`, `a_rocket_nose`) | White rocket body, seen from everywhere on A and long |
| Blast wall | `a_site` (`a_blast_wall`) | The only yellow-black striped object on the map |
| Cart | `a_site` (`a_cart`) | Low steel cart in front of the tower |
| Pit | `long_mid` (`long_box`) | Long's middle yard with the big box breaking the line |
| Short | `a_short` | Concrete corridor from mid onto the pad |
| Stage | `hangar` (`mid_stage`) | White rocket stage on its transporter |
| Containers | `mid` (`mid_crate`), `mid_s` (`mid_s_box`) | Blue shipping containers in the yard |
| Airlock | `b_airlock` | Low green-grey room before the tunnel mouth |
| Satellite | `b_site` (`b_sat`, `b_stand`, `b_panel_*`) | White body with blue solar panels in the middle of the lab |
| Racks | `b_site` (`b_rack_w`, `b_rack_e`) | Lab computer racks along the walls |
| Control / Balcony | `b_control`, `b_balcony` | Control centre with consoles (`b_console`) and its window over the lab |

## 4. Palette and materials
- **Primary colours:** concrete grey (≈ #8c8a86), lab white (≈ #e8ecee), asphalt (≈ #3c3c44).
- **Accents (orientation):** A = rocket white + warning yellow (≈ #e8c020, blast wall only), B = clean white + lab green-grey (≈ #7fa29a), mid = blue-grey steel (≈ #72767c) + container blue (≈ #2a55b0), CT = cool grey.
- **Materials:** A: poured concrete, plain cast concrete walls, light steel (tower, steps). B: white tile, white panels, ceiling tiles, lab racks. Mid: concrete, steel-plate hangar walls, containers. A cover: cool grey crates. T: asphalt, plain concrete walls, grey steel panel cover, plain concrete ceilings. CT: pavers, light panelled walls.
- **Picking textures (style review 2026-10-18):** walls and cover behind players are chosen by the catalog's mean rgb (blue >= red, small channel spread, mean ~110-160), then checked plain on a contact sheet.
- **Readability rules (from de_forge01):** T clothing is tan/brown/orange, CT dark blue: no tan, rust or orange on big surfaces T stands in front of; plain surfaces over mottled ones; no busy repeating textures on big faces; no metal floors.
- **Texture rules:** WAD3, 8-bit, multiples of 16, at most **24** unique textures in play areas (today 21). The game's own WADs only (cstrike, valve/halflife), referenced in the map's `wad` key, never embedded.

## 5. Light
- **Global (`light_environment`):** morning sun from the south-east (pitch -45, yaw 135), warm white (255 244 225), brightness 300 (raised from 260 after the style review), ambient 100; sky `grnplsnt` (clear blue). Check in game that the light pad does not burn out; lower to ≈ 260 if it does.
- **Per zone:** lab bright and cool (point lights 200 + the whole ceiling `FIFTIES_CEIL01` as a weak texlight, a clean room's luminous ceiling); B service corridors cool 260; T tunnels near-neutral white (250 245 235, cooled so the grey walls do not turn beige) 320 at 256 spacing (they are low and long); CT cool; mid and A neutral. Lights on the four chokepoint doors.
- **Readability:** players must be visible in every play area; the brightness map has no dark zones (FITNESS.md). Contrast between player and background goes before mood.
- **Compile profile final:** `-extra -bounce 8` (config/pipeline.yaml).

## 6. Details and sound
- **Decals (`infodecal`):** hazard signs on the pad, "CLEAN ROOM" at the airlock, arrows to A/B along routes. Never in main sight lines or where they can be mistaken for players.
- **Models:** only models the game ships, sparingly (r_speeds < ~800 wpoly). Candidates: pallets or barrels in the yard, a crane hook in the hangar.
- **Architecture details (`func_detail`):** pipes and cable trays in the tunnels, door frames at the chokes. Must not change walkability or sight lines (geometry is frozen: only after a human decision).
- **Ambient sound:** none (de_forge01 experience: irritating in game). Only the game's own sounds and room reverb (`env_sound`).

## 7. Style-review checklist (Claude uses this per screenshot)
- [ ] Matches the zone's palette (A sunlit concrete + white rocket, B white clean room)
- [ ] Landmark visible and clear from the main entrance (rocket, satellite, stage)
- [ ] No obviously wrong texture alignment or stretching (rocket and stage textures on their cover)
- [ ] No texture repetition that looks patterned over big faces (watch mid's panels and the lab floor)
- [ ] Light matches the zone; no dark play areas; the outdoor pad not burned out
- [ ] Players stand out against floors and walls (no tan behind T, no dark blue behind CT)
- [ ] No visual noise around important angles (chokepoints, site entrances)

**Severity per finding:** critical (affects gameplay/readability) / medium (breaks style) / cosmetic.
