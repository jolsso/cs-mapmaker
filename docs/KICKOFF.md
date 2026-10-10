# Kickoff-prompts til Claude Code

Kopiér ind i Claude Code i repo-roden. Én prompt pr. fase.

## Start (Fase 0)
```
Læs CLAUDE.md og alle filer i docs/. Opsummér pipeline, faser og fitness-kriterier
i 10 linjer, og list alle punkter markeret ⚠️ VERIFICÉR. Lav derefter en plan for
Fase 0 og start på den. Stop når Fase 0's acceptkriterier er opfyldt, og rapportér.
```

## Næste fase
```
Fase <N> er godkendt. Læs ROADMAP.md for Fase <N+1>, verificér relevante
⚠️-punkter mod officiel dokumentation, lav en plan og implementér. Stop ved
acceptkriterierne eller ved en gate.
```

## Ved en gate
```
Vi er ved Gate <A/B/C>. Lav en opsummering til mig: hvad er bygget, nøgletal,
billeder jeg skal se på, åbne risici, og hvilke beslutninger jeg skal låse i FITNESS.md.
```

## Autonomt loop (Fase 6+)
```
Kør `make loop MAP=<navn>` inden for budgettet i config/fitness.yaml. Respektér
låste beslutninger og tilladte ændringer i FITNESS.md. Log hver iteration i runs/.
Stop ved stopkriterie eller gate og skriv en opsummering.
```
