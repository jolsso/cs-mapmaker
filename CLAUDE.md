# CLAUDE.md – CS 1.6 MapForge

Projekt: Et automatiseret, end-to-end pipeline til at designe, compile, teste og forbedre Counter-Strike 1.6 maps (GoldSrc) med et feedback-loop.

## Mål
Producér maps der er **teknisk fejlfri, rimeligt balancerede, velbelyste og visuelt konsistente** – uden manuelt rutinearbejde. Mennesket sidder ved gates, ikke i hver iteration.

## Læs disse først
- `docs/ARCHITECTURE.md` – pipeline, komponenter, repo-struktur
- `docs/ROADMAP.md` – faser og acceptkriterier (arbejd fase for fase)
- `docs/FITNESS.md` – hvad "bedre" betyder, stopkriterier, låste beslutninger
- `docs/TRACKER_SPEC.md` – AMXX tracker-plugin og CSV-skema
- `docs/ART_DIRECTION.md` – world bible + stilguide (udfyldes pr. map)

## Arbejdsregler
1. **Én fase ad gangen.** Start ikke på næste fase før den aktuelle opfylder sine acceptkriterier i ROADMAP.md.
2. **Verificér før du antager.** Værktøjers CLI-flag, kommandoer og formater (SDHLT, moderngl, YaPB, HLDS) skal tjekkes mod deres dokumentation eller `--help`. Punkter markeret `⚠️ VERIFICÉR` i docs er ikke bekræftede.
3. **Rør aldrig låste beslutninger** (se FITNESS.md → "Låste beslutninger") uden eksplicit godkendelse.
4. **Alt deterministisk skal være scriptet.** Ingen manuelle trin i loopet; hver iteration skal kunne genskabes fra kode + config.
5. **Log hver iteration** i `runs/<map>/<iteration>/` med: .map-diff, compile-log, metrikker (JSON), renders/screenshots, og en kort `NOTES.md` om hvad der blev ændret og hvorfor.
6. **Små, målrettede ændringer pr. iteration.** Ændr én ting ad gangen når det er muligt, så effekten kan måles.
7. **Commit efter hver feature** (lokalt; push kun på forespørgsel). Rækkefølge: `./mf test` + `./mf lint` grønne → docs/ROADMAP opdateret → oversigtssiden genudgivet → commit. Saml ikke en hel fase i ét commit.
8. **Opdatér oversigtssiden** `docs/overview.html` (arkitektur + roadmap) efter hver implementeret roadmap-feature, og genudgiv den til samme artifact-URL: https://claude.ai/artifact/B1mxnr1kLUJGD8de4ruDfX
9. **Stop ved gates** (se ROADMAP.md) og skriv en opsummering til mennesket i stedet for at fortsætte.

## GoldSrc-fakta (design-normer)
- 1 unit ≈ 1 inch. Grid: arbejd på 16/8-grid; aldrig off-grid vertices.
- Spillerhull: 32×32×72 (stående), 32×32×36 (crouch). Max trinhøjde: 18 units.
- Korridorer/døre: min. 64 bred, 96–128 høj som tommelfingerregel. Bevidst strengere end Valves egne maps (typisk 40–56 brede passager) – besluttet 2026-10-10, se `docs/CALIBRATION.md`.
- Brushes skal være konvekse. Ingen leaks: hele spilområdet skal være forseglet af world brushes.
- Map-grænser: ±4096 units.
- Hold øje med engine-limits (clipnodes, planes, entities/edicts, texture memory) og r_speeds (wpoly). Mål: < ~800 wpoly i spilområder (retningslinje).
- .map-format: Valve 220 (Half-Life). Teksturer i WAD3, 8-bit palettiseret, dimensioner i multipla af 16.

## Kodekonventioner
- Python 3.11+ til generator, analyse og orkestrering. Type hints, `ruff` + `pytest`.
- Pawn (AMX Mod X) til server-plugins i `server/plugins/`.
- Python-pakken hedder `mapforge/` (undermoduler pr. pipeline-trin); moduler køres med `uv run python -m mapforge.<…>`.
- Docker til alt deterministisk (forge), HLDS og render-miljø. Ingen hardcodede stier – brug `config/*.yaml`. Filer skal have LF-linjeskift (`.gitattributes`), da de bruges i Linux-containere.
- Ingen ophavsretsbeskyttede assets fra andre spil i repoet. Kun egne/fri-licens teksturer, med licens noteret i `assets/LICENSES.md`.

## Kommandoer (opdatér når de findes)
**Docker er den officielle vej.** Værten skal kun have Docker. `mf` (sh) / `mf.ps1` (Windows) kører en task i `forge`-containeren (`docker/forge/Dockerfile`, `compose.yaml`) med repoet mountet på `/work`; imaget genbygges automatisk (cached) når `uv.lock` eller `config/pipeline.yaml` ændres. Task runner er [go-task](https://taskfile.dev) (`Taskfile.yml`).
```bash
./mf compile MAP=<navn>       # CSG→BSP→VIS→RAD (PROFILE=fast|final, default fast)
./mf test                     # pytest (inkl. compile-smoke-test med Linux-binaries)
./mf lint                     # ruff check + format --check
./mf validate MAP=<navn>      # compile + validering → build/<map>/validation.json (exit 1 ved errors)
./mf validate MAP=de_dust2 SOURCE=reference   # kun .bsp fra referencemaps (ingen compile/.map)
./mf refmaps                  # pak test_maps/*.rar ud og list referencemaps
./mf render MAP=<navn>        # top-down + kameraviews        (Fase 3)
./mf simulate MAP=<navn>      # HLDS + YaPB, N runder         (Fase 4)
./mf analyze MAP=<navn>       # heatmaps + metrikker          (Fase 5)
./mf loop MAP=<navn>          # fuld iteration                (Fase 6)
```
Fallback til debugging på værten: `uv run task <navn>` (samme tasks, Windows-binaries i `tools/`). Kun Docker-vejen tæller for acceptkriterier.
- Imaget er Debian trixie: SDHLT 1.3.0's Linux-binaries kræver glibc ≥ 2.38 (bookworm har 2.36).
- Compilerne bages ind i imaget under `/opt/tools` (`MAPFORGE_TOOLS_DIR`), venv ligger i `/opt/venv` – intet i containeren skriver til repoets `.venv` eller `tools/`.
- **Referencemaps** (officielle fra din Half-Life-installation via `HL_DIR` i `.env`, community-maps i `test_maps/`) bruges kun til test og kalibrering. De er ophavsretsbeskyttede/ukendt licens: mountes read-only, pakkes ud i `build/refmaps/`, og intet fra dem må committes.
- Projektet er ikke en installeret pakke (`[tool.uv] package = false`); moduler køres fra repo-roden.

## Compiler
Vi bruger **SDHLT** (github.com/seedee/SDHLT), den vedligeholdte fork af Vluzacn's ZHLT v34 (VHLT). Version, URL, SHA256 og flag pr. profil står i `config/pipeline.yaml`; maskinspecifikke overrides i `config/pipeline.local.yaml` (gitignored).
- Flag er verificeret mod `-help` for v1.3.0. `-console 0` på Windows forhindrer pop-up-konsol.
- hlbsp returnerer exit 0 selv ved leak – compile-scriptet tjekker derfor `LEAK` i output og `.pts`/`.lin`-filer.
- `wad`-nøglen i en .map indeholder kun filnavne; compile-scriptet slår dem op i `paths.wad_dirs` og embedder `wad.include` i .bsp med `-wadinclude`.
