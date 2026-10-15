# Art Direction – de_forge01

Tema låst 2026-10-15 (Gate B, menneskets valg): **industri**. Geometrien er frosset i v006, så art pass ændrer kun teksturer, lys, decals, lyd og pynt uden betydning for gangbarhed. Navne i parentes er områder og cover i `layout.yaml`.

## 1. World bible
- **Mapnavn:** de_forge01 ("Smedjen")
- **Setting:** Et nedlagt stålværk i Nordeuropa, sen efterårseftermiddag med lav sol og diset luft. Værket er halvt lukket ned. Ovnen ved A gløder stadig, mens kølehallen ved B står fugtig og kold.
- **Historie i én sætning:** T vil sprænge værkets to sidste funktionsdygtige anlæg, støbepladsen (A) og pumpehallen med kølevand (B), før det sælges til skrot.
- **Hvad fortæller miljøet?** Halvfærdig nedlukning: afspærringer, stablede skrotkasser, slaggespor fra ovnen mod A, vandpytter og rustløbere i B-tunnellerne, oprydningsmarkeringer med spraymaling.
- **Referencer/stemning:** Egne beskrivelser: rustrød stål, sod, varmt ovnlys mod kold beton. Ingen assets fra andre spil.

## 2. Zoner
| Zone | Funktion | Fortælling | Palet | Lys-stemning | Landmark |
|---|---|---|---|---|---|
| T spawn (`t_spawn`) | Udendørs læsseplads | Lastbilernes rampe ved hovedporten | Asfalt, gulmalet stål | Lav sol bagfra, varm | Hovedporten (sydvæg) |
| CT spawn (`ct_spawn`) | Udendørs gård ved administrationen | Vagtpost og parkering | Lys beton, blå skiltning | Kold-neutral, jævn | Vagthuset |
| Mid (`mid`, `mid_s`, `mid_top`) | Åben skrotplads + overdækket krydsning | Skrotsortering | Grå beton, rust | Neutral dagslys, mid_top lidt varmere | Transformatoren (`mid_box`) |
| A site (`a_site`, hævet 32) | Støbepladsen udendørs | Ovnens udslip, ingots køler af | Rustorange, sod, varmt stål | **Varm/orange** glød fra ovnvæggen | Ingot-stablen (`a_box_big`) |
| B site (`b_site`) | Pumpehallen indendørs | Kølevand til ovnen | Kold beton, teal-malede rør | **Kold/blå**, fugtig | Køletårnenes søjler (`b_pillar_w`, `b_pillar_e`) |
| Forbindelser | Long, tunneler, short | Transportveje og kabelkanaler | Følger nærmeste site (A varm, B kold); T-siden gul markering | Gangbar overalt, ingen mørke zoner | Se callouts |

**Regel:** Hver site og hver hovedrute har ét unikt, genkendeligt landmark (callout-venligt).

## 3. Callouts
| Navn | Zone | Hvorfor genkendeligt |
|---|---|---|
| Porten | `t_spawn` | Gul-sort stribet hovedport bag T-spawn |
| Slaggevognen | `a_long` (`long_box`) | Sodsort kasse midt på long, varmt lys fra A ender her |
| Ingot-stablen | `a_site` (`a_box_big`, `a_box_small`) | Den store stak ved A, orangeglødende flader |
| Ovnvæggen | `a_site` (`a_wall`) | Væg ved long-indgangen med ovnlys (texlight) |
| Transformatoren | `mid` (`mid_box`) | Grøn-grå kasse med advarselsskilt midt på mid |
| Broen | `mid_top` | Overdækket krydsning; varmere lys end mid |
| Kabelkanalen | `b_tunnels` (`b_tun_wall`) | Lav, våd tunnel med kabelbakker og teal-lys |
| Søjlerne | `b_site` (`b_pillar_w`, `b_pillar_e`) | To høje teal-malede køletårnssøjler |
| Platformen | `b_site` (`b_platform`) | Lav pumpeplatform mellem søjlerne |
| Vagthuset | `ct_spawn` | Lyst hjørne med blå skiltning |

## 4. Palet og materialer
- **Primærfarver:** rustrød (≈ #8a3b1e), sod-grå (≈ #2e2e2e), betongrå (≈ #8c8a84).
- **Accentfarver (orientering):** A = varm orange (≈ #e8792f), B = kold teal (≈ #3fa3a8), T-side = signalgul (≈ #e0b030), CT-side = blå (≈ #4c8fe0).
- **Materialer:** A: rusten stålplade, sodet beton, slagge. B: våd beton, malede rør, riste. Mid: beton, bølgeblik, rust. Spawns: asfalt (T), lys beton (CT).
- **Tekstur-regler:** WAD3, 8-bit, multipla af 16, højst **24** unikke teksturer i spilområder. Kun egne/CC0 (procedurelle eller fra egne billeder via fase 7's tekstur-pipeline), noteret i `assets/LICENSES.md`.

## 5. Lys
- **Global (`light_environment`):** lav eftermiddagssol fra sydvest (pitch ≈ -35, yaw ≈ 225), varm hvid-orange (≈ 255 220 180), lysstyrke lavere end i dag (≈ 220), så udendørs flader ikke brænder ud (review-fund på andre maps). Himmel: diset.
- **Pr. zone:** A varm (ovnglød fra `a_wall` som texlight, orange lysfarve); B kold (teal lysfarve, lysstofrør som texlights i loftet); tunneler svagt teal; mid og spawns neutrale.
- **Læsbarhed:** spillere skal kunne ses i alle spilområder; lysstyrkekortet må ikke have mørke spilzoner (FITNESS.md). Kontrast mellem spillermodel og baggrund går forud for stemning.
- **Compile-profil final:** `-extra -bounce 8` (config/pipeline.yaml). Gamma justeres kun, hvis lysstyrkekortet kræver det.

## 6. Detaljer og lyd
- **Decals (`infodecal`):** advarselsskilte ved ovnen (A), "KØLEVAND"-markering i B, pile/spraymaling langs ruter, rustløbere i tunnellerne. Aldrig i hovedsigtelinjer eller hvor de kan forveksles med spillere.
- **Sprites/modeller:** kun modeller, der følger med spillet (fase 7, ⚠️ VERIFICÉR), sparsomt pga. r_speeds (< ~800 wpoly).
- **Arkitekturdetaljer (`func_detail`):** rørføringer langs vægge, dørkarme ved chokepoints, kabelbakker i tunnellerne. Må ikke ændre gangbarhed eller sigtelinjer.
- **Ambient lyd:** ingen. Prøvet 2026-10-15 (ovnbrummen, pumper, drypvand, vind) – irriterende i spillet, så det er fravalgt. Kun spillets egne lyde (skridt, våben) og rumklang (`env_sound`).

## 7. Stilreview-tjekliste (Claude bruger denne pr. screenshot)
- [ ] Matcher zonens palet og materialer (A varm/rust, B kold/teal)
- [ ] Landmark synligt og tydeligt fra hovedindgang
- [ ] Ingen åbenlyst forkert tekstur-alignment eller strækning
- [ ] Ingen tekstur-gentagelse der virker mønstret over store flader
- [ ] Lys-stemning matcher zonen; ingen mørke spilområder; udendørs flader ikke udbrændte
- [ ] Fortællingsspor er til stede, men skjuler ikke spillere
- [ ] Ingen visuel støj omkring vigtige angles (chokepoints, site-indgange)

**Alvorlighed pr. fund:** kritisk (påvirker gameplay/læsbarhed) / middel (bryder stil) / kosmetisk.
