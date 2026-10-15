# Træning af graf-modellerne (Fase 8g)

Hvordan topologier (`topology.yaml`, MAPMAKER.md → Graf-laget) bliver til træningsdata, og hvordan de to modeller trænes, evalueres og tages i brug:

- **Surrogat-kritiker:** graf → BSP-niveau-metrikker + indlejrbarhed (regression/klassifikation på hele grafen).
- **Graf-generator:** intent → ny topologi (sekvensmodel over en serialiseret graf).
- **Præferencemodel** (senere): par af topologier → hvilken foretrak mennesket.

Samme regler som resten af repoet: alt er scriptet og reproducerbart fra kode + config + datasæt-manifest (CLAUDE.md regel 4), alt kører i Docker, og intet afledt af referencemaps forlader maskinen.

## 1. Datasæt

### Poster
Én post pr. evalueret topologi, gemt som JSONL i `build/topologies/<kilde>/*.jsonl`:

```json
{
  "id": "elites-0412-7f3a",
  "source": "generated",
  "family": "elites-0412",
  "license": "generated",
  "tier": null,
  "topology": { "...": "topology.yaml som JSON" },
  "intent": {"archetype": "asymmetric", "size": "medium", "pace": "medium", "sightlines": {"long": "few", "cqb": "many"}},
  "labels": {
    "graph": {"t_to_a": 19.2, "t_to_b": 16.8, "ct_margin_a": 4.1, "rotation": 12.5, "complexity_c": 11},
    "bsp": {"t_to_a": 20.1, "t_to_b": 17.5, "rotation": 13.2, "territory_ct": 0.63, "share_long": 0.18, "share_close": 0.41},
    "fit": {"ok": true, "stretch": 0.12},
    "review": {"pass": true, "score": 3.8},
    "human": null
  },
  "provenance": {"commit": "121c667", "created": "2026-10-20T14:02", "bsp_sha256": "…"}
}
```

`labels.bsp`, `fit`, `review` og `human` er `null`, når trinnet ikke er kørt. Bot-metrikker gemmes som `labels.bots` til diagnostik, men er **aldrig** et træningsmål (FITNESS → Goodhart).

| Kilde (`source`) | `license` | Må committes |
|---|---|---|
| `own` – egne maps og alle loop-versioner | own | ja |
| `generated` – MAP-Elites-arkiv, generator-samples | generated | ja (men stort; gitignored som standard) |
| `refmap` tier A – de 15 officielle de_-maps | reference | **nej**, kun `build/` |
| `refmap` tier B – community-maps | reference | **nej**, kun `build/` |
| `human` – Gate A-valg, Gate C-skemaer | own | ja |

### Tiers
`tier` sættes for referencemaps: **A** = officielle (navneliste i `config/pipeline.yaml` → `refmaps.tiers.A`), **B** = alle andre referencemaps; override pr. map samme sted. `null` for egne og genererede.

| Brug | Tier A | Tier B |
|---|---|---|
| Surrogat | kun test | train/val (efter familie) + separat test-rapport |
| Generator, finetuning | aldrig træning | sample-vægt 1 |
| Realisme-fordeling og nyhedskrav | vægt 3 | vægt 1 |
| Arketype-klynger | med, medoider foretrækkes | med |
| Præference | svag prior: A ≻ B-par med lav vægt (tier følger kilden, ikke en vurdering af hvert map) | – |

### Manifest og versioner
`./mf dataset build` samler posterne til `build/datasets/<navn>-v<N>/` med `manifest.json`: kilder, antal, filtre, sha256 pr. fil og en samlet hash. En model peger altid på et manifest, aldrig på "de nuværende filer".

### Splits efter familie, ikke tilfældigt
Varianter af det samme map (loop-versioner, mappack-kloner af dust2, nabo-celler i MAP-Elites) ligner hinanden så meget, at et tilfældigt split lækker. `family` grupperer dem, og hele familier fordeles på train/val/test (80/10/10, fast seed). **Tier A er altid i test** – de er det, vi helst vil kunne forudsige og ligne. Tier B fordeles efter familie som alt andet.

## 2. Graf → tensorer (surrogaten)

PyTorch Geometric `Data` pr. topologi:

| Del | Features |
|---|---|
| Node | one-hot rolle (8), one-hot størrelse (4), niveau (−2…+2, skaleret), er site A / B, er spawn T / CT |
| Kant | one-hot type (8), længde / 4096, bredde-klasse, `oneway`; rettede kanter (en `drop` findes kun den ene vej), `window` med som kant men markeret ikke-gangbar |
| Graf | intent (arketype, størrelse, tempo, sigtelinjer) som global vektor |

Mål (`y`) normaliseres pr. kolonne (gennemsnit/std fra train-split, gemt med modellen).

## 3. Surrogat-kritiker

- **Arkitektur:** GINE (kant-features i message passing), 4 lag, hidden 128, residual + LayerNorm; readout = mean + max + sum over noder, konkateneret med intent → MLP-hoveder: regression (timings, rotation, territorium, sigtelinje-andele, Fit-stræk) og klassifikation (Fit lykkes, Review består).
- **Tab:** Huber på normaliserede regressionsmål (maskeret, hvor label er `null`) + BCE på klassifikation; vægte i `config/train.yaml`.
- **Ensemble:** 5 modeller med forskellige seeds. Middel = forudsigelse, spredning = usikkerhed.
- **Træning:** AdamW, lr 1e-3 med cosine, 200 epoker, early stopping på val-tab. Datamængden er lille: CPU er nok (minutter).
- **Evaluering (test-split):** MAE i sekunder og R² pr. timing-mål, AUROC for Fit/Review, **kalibrering** (andel af sande værdier inden for ensemblets ±2σ, mål ~95 %). Rapporteres særskilt for tier A og tier B.
- **Baseline:** graf-niveau-evaluatoren alene (ingen læring). Surrogaten skal slå den på BSP-mål, ellers bruges den ikke.

**Active learning:** i hver MAP-Elites-kampagne sendes de kandidater med størst ensemble-spredning (og høj forventet kvalitet) gennem BSP-niveauet. Deres labels lægges i næste datasæt-version.

## 4. Graf-generator

### Serialisering
En graf har mange mulige rækkefølger. Kanonisk form: BFS fra T-spawn med naboer sorteret efter (rolle, niveau, størrelse); noder omnummereres i den rækkefølge; længder kvantiseres i 64-units-bins (0–63 bins).

```
<BOS> <ARCH=asymmetric> <SIZE=medium> <PACE=medium> <LONG=few> <CQB=many>
<N> t_spawn S=L L=0 </N>
<N> mid S=M L=0 </N>  <E> 0 1 door len=22 w=normal </E>
<N> choke S=S L=0 </N> <E> 1 2 door len=14 w=narrow </E>
<N> site=B S=L L=-1 </N> <E> 2 3 ramp len=9 </E>
…
<EOS>
```

Kanter udsendes, så snart begge ender findes (kun bagudrettede referencer). Ordforråd ≈ 150 tokens.

### Model
Decoder-only transformer, 6 lag, d = 256, 8 heads, kontekst 512 tokens (≈ 5 mio. parametre). Intent er prefix-tokens, så samme model kan betinges eller samples frit (intent-tokens droppes tilfældigt 10 % af tiden under træning). Et kvalitets-token `<Q=…>` (`elite` for arkivets top-celler, `B` for tier B, `gen` for resten) lader modellen lære forskellen; i drift samples der med det bedste token.

### Begrænset dekodning
En tilstandsmaskine følger med under sampling og maskerer ugyldige tokens: kanter kun mellem eksisterende noder, præcis én af hver spawn og to sites, grad ≤ 4, ingen kant spawn ↔ site. Det, der kun kan tjekkes på den færdige graf (sammenhæng, nåbarhed, site-indgange, planaritet pr. niveau), tjekkes efter `<EOS>`. Ugyldige grafer **afvises og tælles** – de repareres ikke, så validitetsraten forbliver en ærlig metrik.

### Træningsløkke
1. **Prætræning** på MAP-Elites-arkivet: teacher forcing, cross-entropy. Augmentering: A/B-ombytning af sites, tilfældig gyldig BFS-rækkefølge ved lige ranger (lærer modellen at rækkefølgen er ligegyldig).
2. **Finetuning** på `own` + `refmap` (lav lr, få epoker), så fordelingen trækkes mod rigtige maps.
3. **Expert iteration**, R runder: sample 5000 betinget på intents fra arkivet → afvis ugyldige og dem, der bryder nyhedskravet → scor med evaluator + surrogat → finetun 1 epoke på top 10 % + 20 % replay fra det oprindelige datasæt (mod mode-kollaps).
4. Sampling i drift: temperatur 0,8–1,0, nucleus 0,95.

### Evaluering
| Metrik | Hvad | Mål |
|---|---|---|
| Validitet | andel, der består invarianterne uden reparation | ≥ 80 % |
| Unikhed | andel forskellige WL-hashes blandt 1000 samples | ≥ 90 % |
| Nyhed | andel med graf-edit-distance ≥ τ til alt i train + refmaps | 100 % efter filter; rå andel rapporteres |
| Kvalitet | fordeling af graf-niveau-regelstraf vs. MAP-Elites-arkivet | ikke dårligere |
| Dækning | andel af MAP-Elites' adfærdsceller, generatoren rammer | rapporteres |
| Realisme | afstand mellem fordelinger af graf-statistik (grad, C, indgange, niveauer) og tier A (og tier B separat) | rapporteres |
| **Accept** | Review-godkendte kandidater pr. compute-time, ende-til-ende | > MAP-Elites alene |

### Alternativ
Diskret graf-diffusion (DiGress) i stedet for sekvensmodellen: stærkere global struktur, men sværere at betinge og at håndhæve invarianter under sampling. Afprøves kun, hvis transformeren ikke når validitets- eller realisme-målene.

## 5. Præferencemodel (senere)

Bradley-Terry på par fra Gate A ("valgte kandidat 3 frem for 1, 2, 4") og Gate C-scorer, med surrogatens graf-embedding som input og kraftig regularisering. Bruges først som tie-breaker i Sketcher, når der er ≥ 50 par, og aldrig som eneste fitness.

## 6. Infrastruktur

- **Image** `train` (`docker/train/Dockerfile`): PyTorch (CPU) + PyTorch Geometric + networkx, pinnet i `uv.lock`. Valgfri CUDA via compose-profil `gpu` ⚠️ VERIFICÉR GPU-passthrough på værten. Surrogaten trænes fint på CPU; generatoren kan kræve GPU ved store arkiver.
- **Config:** `config/train.yaml` – seeds, hyperparametre, tab-vægte, splits, τ for nyhed.
- **Reproducerbarhed:** faste seeds, `torch.use_deterministic_algorithms(True)` hvor muligt, datasæt-manifest-hash og git-commit gemt med modellen.
- **Model-register:** `build/models/<surrogate|generator>/v<N>/` med `model.pt`, `config.yaml`, `metrics.json`, `manifest.json` (datasættet), `MODEL_CARD.md` (data, metrikker, kendte svagheder). Gitignored – modeller trænet på referencemap-data deles ikke.
- **Promotion:** en ny version bliver `current` kun hvis den slår den nuværende på den faste test-split (surrogat: BSP-MAE; generator: accept-metrikken). Ellers beholdes den gamle; rollback = flyt `current`.
- **Website:** en side "Modeller" med træningskurver, test-metrikker pr. version og eksempel-samples (radar + graf) – samme inline-SVG-charts som resten af sitet.

## 7. Retræning

| Model | Retrænes når |
|---|---|
| Surrogat | ≥ 200 nye BSP-labels, eller drift: MAE på de seneste 50 compilede kandidater > 1,5 × test-MAE |
| Generator | efter hver MAP-Elites-kampagne, eller når surrogaten er promoveret (scoren ændrer sig) |
| Præference | efter hver Gate A/C med nye par |

## 8. Kommandoer

```bash
./mf refgraphs                         # referencemaps (BSP) → build/topologies/refmap/
./mf dataset build NAME=topo           # → build/datasets/topo-v<N>/ med manifest
./mf train surrogate                   # ensemble på seneste datasæt → build/models/surrogate/v<N>/
./mf train generator -- --stage pretrain|finetune|expert --rounds 3
./mf models eval surrogate|generator   # fast test-split, sammenlign med current
./mf models promote surrogate v<N>
./mf sample -- --intent maps/<map>/intent.json --n 200   # generator-samples → Sketcher
```
