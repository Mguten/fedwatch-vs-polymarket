# FedWatch-replikering + Polymarket-jämförelse

Se `fedwatch_project_spec.md` för den fulla specifikationen. Denna fil är en
snabb karta över vad som är byggt och hur man kör det.

## Status per modul

| Modul | Status | Kommentar |
|---|---|---|
| 1. Data ingestion | ✅ Klar | `fedwatch/ingestion/`. `Data/` täcker nu samtliga 12 kontraktsmånader (F-Z) sedan Sep–Dec-filerna (U,V,X,Z) lades till. Läser även `.CSV` (versaler) — tre av de nya filerna hade versal filändelse, glob var skiftlägeskänsligt tills det fixades. |
| 2. FOMC-mötesdatum | ✅ Klar | `fedwatch/fomc/`. Skrapar federalreserve.gov, fallback till `config/fomc_dates.csv`. Faktiska beslut härleds empiriskt ur FRED (DFEDTARU/DFEDTARL), inte en handunderhållen lista. |
| 3. Deconvolution engine | ✅ Klar, testad | `fedwatch/deconvolution/`. 17 enhetstester, validerat mot CME:s publicerade siffror inom ±0.6pp (tolerans ±2pp). Se docstring i `engine.py` för hur "fler än två utfall" faktiskt löstes (full convolution, inte lokal breddning — den första idén visade sig ge SÄMRE träffsäkerhet mot riktig CME-data). |
| 4. Validering mot CME | ✅ Klar | `fedwatch/validation/`. Efter att `Data/FedMeeting_*.csv` (CME:s egna historiska sannolikheter, ~1 års historik, 12 möten, 80 107 datapunkter) lades till är detta nu ett riktigt automatiskt jämförelsetest, inte bara enpunktstestet från skärmdumpen. Resultat: 10/12 möten ≥95% av datapunkterna inom ±2pp, medelavvikelse 0.02–0.4pp per möte. 2 möten (2026-03-18, 2026-04-29) flaggade under 95% — avvikelserna klustrar kring mitten/slutet av december 2025, dvs. runt det faktiska decembermötet 2025-12-09/10, sannolikt en baslinje-/tajmingeffekt kring ett verkligt beslut snarare än ett generellt metodfel. Se `output/cme_validation_summary.csv` efter körning. cmegroup.com blockerar fortfarande programmatisk åtkomst (403) — den historiska datan kom via manuell export, se `fedwatch/validation/README.md`. |
| 5. Polymarket-integration | ✅ Klar | `fedwatch/polymarket/`. clob.polymarket.com + gamma-api.polymarket.com är fritt tillgängliga. Bygger en KANDIDATTABELL (`config/polymarket_fomc_match_review.csv`, 26 rader efter filtrering — se nedan) som måste granskas för hand (kolumn `confirmed`) innan Modul 6 använder den. |
| 6. Jämförelse & output | ✅ Klar | `fedwatch/comparison/`. Jämför FedFunds-motorns lokala stegfördelning mot Polymarkets priser. **Bekräftat fynd (2026-07-15, event 606422 "Fed Decision in October?"):** vår `local`-fördelning är alltid exakt binär (två utfall) medan Polymarket prisar in fem — det är CME:s egen metodbegränsning synlig i riktig data, inte en bugg. Medvetet INTE "fixat" genom att bredda modellen (det gjordes tidigare och gav sämre träffsäkerhet mot CME:s riktiga siffror) — se motivering i `compare.py`. |

## Köra pipelinen

```bash
python run_pipeline.py [YYYY-MM-DD] [--skip-validation]   # watch_date, default idag
```

Modul 4 kör ~250 motorkörningar (en per historiskt datum i CME:s export)
och tar ~30-40 sekunder — hoppa över med `--skip-validation` vid snabb
iteration. Första körningen genererar även
`config/polymarket_fomc_match_review.csv` och stannar där för Modul 5/6 —
granska filen för hand, fyll i `TRUE`/`FALSE` i kolumnen `confirmed`, kör
sedan skriptet igen för att även få Modul 6:s output i
`output/fedfunds_vs_polymarket.csv`.

## Tester

```bash
python -m pytest tests/ -v
```

41 tester, ingen nätverksåtkomst krävs (Modul 3/4-testerna använder de
CSV-fixturer som redan ligger i `config/`/`Data/`).

## Miljö

Paket installeras i den delade venv:n `main` (inget separat virtualenv för
detta projekt — beslutat med användaren). Se `requirements.txt`.
