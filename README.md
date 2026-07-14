# FedWatch-replikering + Polymarket-jämförelse

Se `fedwatch_project_spec.md` för den fulla specifikationen. Denna fil är en
snabb karta över vad som är byggt och hur man kör det.

## Status per modul

| Modul | Status | Kommentar |
|---|---|---|
| 1. Data ingestion | ✅ Klar | `fedwatch/ingestion/`. **OBS: `Data/` täcker bara kontraktsmånaderna Jan–Aug (F,G,H,J,K,M,N,Q) — Sep–Dec (U,V,X,Z) saknas helt.** Möten i de månaderna kan inte beräknas förrän fler kontraktsfiler läggs till. |
| 2. FOMC-mötesdatum | ✅ Klar | `fedwatch/fomc/`. Skrapar federalreserve.gov, fallback till `config/fomc_dates.csv`. Faktiska beslut härleds empiriskt ur FRED (DFEDTARU/DFEDTARL), inte en handunderhållen lista. |
| 3. Deconvolution engine | ✅ Klar, testad | `fedwatch/deconvolution/`. 17 enhetstester, validerat mot CME:s publicerade siffror inom ±0.6pp (tolerans ±2pp). Se docstring i `engine.py` för hur "fler än två utfall" faktiskt löstes (full convolution, inte lokal breddning — den första idén visade sig ge SÄMRE träffsäkerhet mot riktig CME-data). |
| 4. Validering mot CME | ⏸️ Pausad | `fedwatch/validation/README.md`. cmegroup.com blockerar programmatisk åtkomst (403). Kräver manuell export eller headless-browser-automatisering — se README för detaljer. |
| 5. Polymarket-integration | ✅ Klar | `fedwatch/polymarket/`. clob.polymarket.com + gamma-api.polymarket.com är fritt tillgängliga. Bygger en KANDIDATTABELL (`config/polymarket_fomc_match_review.csv`) som måste granskas för hand (kolumn `confirmed`) innan Modul 6 använder den. |
| 6. Jämförelse & output | ✅ Klar | `fedwatch/comparison/`. Jämför FedFunds-motorns lokala stegfördelning (inte den kumulativa CME-konventionen) mot Polymarkets priser — se motivering i `engine.py`. |

## Köra pipelinen

```bash
python run_pipeline.py [YYYY-MM-DD]   # watch_date, default idag
```

Första körningen genererar `config/polymarket_fomc_match_review.csv` och
stannar där — granska filen för hand, fyll i `TRUE`/`FALSE` i kolumnen
`confirmed`, kör sedan skriptet igen för att även få Modul 6:s output i
`output/fedfunds_vs_polymarket.csv`.

## Tester

```bash
python -m pytest tests/ -v
```

34 tester, ingen nätverksåtkomst krävs (Modul 3-testerna använder de
CSV-fixturer som redan ligger i `config/`).

## Miljö

Paket installeras i den delade venv:n `main` (inget separat virtualenv för
detta projekt — beslutat med användaren). Se `requirements.txt`.
