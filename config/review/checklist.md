# Review-tjekliste (pre-sim-gate)

Kig på hvert billede og vurdér punkterne. Rapportér kun det, du faktisk kan se.

## Layout (top-down)
1. Er der to bomb sites, og ligger de i hver sin ende/zone af mappet (ikke oven i hinanden eller i et spawn)?
2. Ligger T- og CT-spawn i hver sin zone, tydeligt adskilt?
3. Har hvert site mindst to indgange (fra T-siden), og kan CT nå begge sites?
4. Er afstanden spawn → site rimeligt balanceret (ingen site lige ved et spawn)?
5. Er der en mid/forbindelse mellem ruterne, eller er mappet bare parallelle korridorer?
6. Ses åbenlyse fejl: huller i geometrien, flydende stykker, rum uden forbindelse, sites/spawns uden for spilområdet?

## Sigtelinjer og cover (kameraer)
7. Er der ekstremt lange, åbne sigtelinjer tværs over mappet fra et spawn eller ind på et site uden cover?
8. Har sites cover (kasser, vægge) – eller er det tomme flader?

## Lys og læsbarhed
9. Er spilområder så mørke, at spillere ikke ville kunne ses (se også topdown_dark.png og validation-data)?
10. Ser teksturer korrekte ud (ingen checkerboard = manglende tekstur, ingen grove strækninger)?

## Alvorlighed
- **critical:** gør mappet uspilleligt eller meningsløst (fx site i spawn, spawns oven i hinanden, rute mangler helt).
- **major:** alvorligt balance- eller læsbarhedsproblem, der skal rettes før simulering (fx et site med kun én indgang, et spawn med direkte sigtelinje ind i det andet).
- **minor:** værd at notere, blokerer ikke (kosmetik, små mørke hjørner).

Officielle Valve-maps (de_dust2, de_nuke, ...) er kendt gode; brug dem ikke som undskyldning, men vurdér det billede, du får.
