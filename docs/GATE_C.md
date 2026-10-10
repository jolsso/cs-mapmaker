# Gate C – menneskelig playtest-protokol

Bot-tal er sanity checks; den egentlige dom over balance, læsbarhed og "sjæl" fældes her (DESIGN_GUIDE.md §9). Protokollen bygger på designforskningen (Exodus, Ølsted et al. 2015, Volcano/FMPONE om Cache).

## Format
- 5v5 (eller 4v4) med erfarne CS 1.6-spillere, mindst 2 halvlege med sideskift (MR15), `mp_c4timer 35`.
- HLTV-demo af alle runder (samme mekanisme som simulering: `./mf simulate -- --watch` eller en almindelig server + HLTV).
- Mindst én session med stærke konkurrencespillere før release (Inferno "wvu moto", Cache: "minute, small fixes").

## Før testen
- Del radar/top-down og et callout-kort (navne fra `landmarks` i layout-spec'en).
- Del ikke `intended_strategies` – vi vil se, om spillerne finder dem selv.

## Under testen (fra demo/log)
- Runde-winrate pr. side, plant-split A/B, retake-succes (plant → CT-sejr).
- Hvilke T-planer blev brugt? Svarer de til `intended_strategies`?
- Tid til første kill pr. chokepoint; hvor døde folk (kill-heatmap, samme analyse som bots).

## Spørgeskema efter testen (Likert 1–5 + fritekst)
1. Vidste du altid, hvor du var? (læsbarhed/orientering)
2. Hvilke steder fik et navn spontant? (callouts)
3. Føltes et site T- eller CT-sidet? Hvilket, og hvorfor?
4. Hvordan føltes rotationerne (for lange / for korte / rigtige)?
5. Var der "spildtid" – løb uden beslutninger?
6. Yndlings- og hadeposition, og hvorfor.
7. Kunne du bruge granater (flash/smoke/HE) meningsfuldt?
8. Vil du spille det igen?
9. Hvad er mapets identitet i én sætning? (tester `concept`)

## Iteration
- Flere varianter: tommel op/ned pr. variant og "er denne bedre end forrige?" (FPSEvolver-princippet); bevar lineage i `history/`.
- Fund fra Gate C skrives som annotationer på map-siden (dashboardet), så loopets Decide arbejder videre på dem – låste beslutninger kræver stadig menneskelig godkendelse.
