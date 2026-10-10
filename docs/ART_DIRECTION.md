# Art Direction – skabelon

Kopiér til `maps/<navn>/ART_DIRECTION.md` og udfyld sammen med mennesket ved Gate A. Claude bruger den som facitliste ved stilreview af screenshots.

## 1. World bible
- **Mapnavn:** de_
- **Setting:** (sted, tid, årstid, vejr, tid på døgnet)
- **Historie i én sætning:** (hvad sker der her, og hvorfor er bomben her?)
- **Hvad fortæller miljøet?** (spor af hændelser: skader, efterladte ting, igangværende arbejde)
- **Referencer/stemning:** (egne beskrivelser eller fotos, ikke assets fra andre spil)

## 2. Zoner
| Zone | Funktion | Fortælling | Palet | Lys-stemning | Landmark |
|---|---|---|---|---|---|
| T spawn | | | | | |
| CT spawn | | | | | |
| Mid | | | | | |
| A site | | | | | |
| B site | | | | | |
| Forbindelser | | | | | |

**Regel:** Hver site og hver hovedrute skal have ét unikt, genkendeligt landmark (callout-venligt).

## 3. Callouts
| Navn | Zone | Hvorfor genkendeligt |
|---|---|---|
| | | |

## 4. Palet og materialer
- **Primærfarver:** 
- **Accentfarver (orientering):** fx A = varm/orange, B = kold/blå
- **Materialer:** (beton, træ, metal, sten …) pr. zone
- **Tekstur-regler:** WAD3, 8-bit, multipla af 16, maks. antal unikke teksturer: __. Kun egne/fri-licens, noteret i `assets/LICENSES.md`.

## 5. Lys
- **Global (`light_environment`):** sol-retning, farve, intensitet, himmel
- **Pr. zone:** varm/kold, kontrast, hovedkilder (lamper, vinduer, texlights)
- **Læsbarhed:** spillere skal kunne ses i alle spilområder (se FITNESS.md → mørke zoner)
- **Compile-profil final:** (bounces, `-extra`, gamma). Flag verificeret mod SDHLT 1.3.0 `-help`: `-extra`, `-bounce #`, `-gamma #`, `-minlight #`, `-ao` findes. Se `config/pipeline.yaml`.

## 6. Detaljer og lyd
- **Decals (`infodecal`):** skilte, graffiti, skader – hvor og hvorfor
- **Sprites/modeller:** begræns pga. r_speeds
- **Ambient lyd (`ambient_generic`):** pr. zone (maskiner, vind, vand …)

## 7. Stilreview-tjekliste (Claude bruger denne pr. screenshot)
- [ ] Matcher zonens palet og materialer
- [ ] Landmark synligt og tydeligt fra hovedindgang
- [ ] Ingen åbenlyst forkert tekstur-alignment eller strækning
- [ ] Ingen tekstur-gentagelse der virker mønstret over store flader
- [ ] Lys-stemning matcher zonen; ingen mørke spilområder
- [ ] Fortællingsspor er til stede, men skjuler ikke spillere
- [ ] Ingen visuel støj omkring vigtige angles

**Alvorlighed pr. fund:** kritisk (påvirker gameplay/læsbarhed) / middel (bryder stil) / kosmetisk.
