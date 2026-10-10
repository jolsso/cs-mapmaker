# Review-tjekliste (pre-sim-gate)

Kig på hvert billede og vurdér punkterne. Rapportér kun det, du faktisk kan se eller læse i validatorens data. Principperne og tallene kommer fra `docs/DESIGN_GUIDE.md`.

## Struktur (top-down + layout-spec)
1. **Hovedveje:** 2–3 tydelige veje fra T-spawn mod sites – ikke flere end 3, og ikke kun én.
2. **Chokepoints:** hver hovedvej har ét chokepoint *før* sitet (korridor, dør, tunnel, gyde eller kampplads med cover). Højst 1–2 indgange pr. chokepoint, og ved 2 skal forsvareren kunne se begge fra samme sted.
3. **Forbindelsesveje** lader T skifte rute uden at gå tilbage til spawn – men går ikke gennem et chokepoint.
4. **Sites:** to bomb sites i hver sin zone, ikke i eller ved et spawn. Hvert site kan nås ad mindst to T-ruter uden om CT-spawn, og CT har mindst lige så mange veje ind (retakes).
5. **Spawns:** T og CT tydeligt adskilt; ingen rute fra mid direkte ind i et spawn; ingen sigtelinje spawn-til-spawn.
6. Åbenlyse fejl: huller, flydende geometri, rum uden forbindelse, sites/spawns uden for spilområdet.

## Timing (validatorens `timing site …`-linjer)
7. T → site mellem ca. 14 og 25 s (officielle maps). Kortere = for kompakt; længere = tomme runder.
8. CT når hvert site mindst ~3 s før T (typisk 7–13 s). CT-spawn ligger gerne tættere på det ene site end det andet.

## Sigtelinjer, cover og spillestile (kameraer + top-down)
9. Ingen ekstremt lange, åbne sigtelinjer uden cover fra et spawn eller ind på et site (døre på række, lige korridorer).
10. Blanding af lange sigtelinjer (snipere) og close-quarters-områder – ikke kun én slags.
11. Sites har cover til både forsvar og efter-plant; højdeforskelle bruges bevidst.

## Lys og læsbarhed
12. Spilområder er ikke så mørke, at spillere ikke kan ses (topdown_dark.png + data).
13. Teksturer ser korrekte ud (ingen checkerboard = manglende tekstur, ingen grove strækninger). Dev-teksturer på et graybox-blockout er forventet.

## Alvorlighed
- **critical:** gør mappet uspilleligt eller meningsløst (site i spawn, spawns oven i hinanden, en rute mangler helt).
- **major:** alvorligt balance- eller flowproblem, der skal rettes før simulering (site med kun én T-indgang, mid direkte ind i spawn, kæmpe sigtelinje ind på et site, T når et site før CT kan stille op).
- **minor:** værd at notere, blokerer ikke (kosmetik, små mørke hjørner, timings lidt uden for det typiske).

Officielle Valve-maps er kendt gode; brug dem ikke som undskyldning, men vurdér det billede, du får.
