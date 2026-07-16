# FedWatch-replikering + Polymarket-jämförelse

Se `fedwatch_project_spec.md` för den fulla specifikationen. Denna fil är en
snabb karta över vad som är byggt och hur man kör det.

## Status per modul

| Modul | Status | Kommentar |
|---|---|---|
| 1. Data ingestion | ✅ Klar | `fedwatch/ingestion/`. `Data/` täcker nu samtliga 12 kontraktsmånader (F-Z) sedan Sep–Dec-filerna (U,V,X,Z) lades till. Läser även `.CSV` (versaler) — tre av de nya filerna hade versal filändelse, glob var skiftlägeskänsligt tills det fixades. |
| 2. FOMC-mötesdatum | ✅ Klar | `fedwatch/fomc/`. Skrapar federalreserve.gov, fallback till `config/fomc_dates.csv`. Faktiska beslut härleds empiriskt ur FRED (DFEDTARU/DFEDTARL), inte en handunderhållen lista. |
| 3. Deconvolution engine | ✅ Klar, testad | `fedwatch/deconvolution/`. 19 enhetstester, validerat mot CME:s publicerade siffror inom ±0.6pp (tolerans ±2pp). Se docstring i `engine.py` för hur "fler än två utfall" faktiskt löstes (full convolution, inte lokal breddning — den första idén visade sig ge SÄMRE träffsäkerhet mot riktig CME-data). **2026-07-15:** fixade en prispropageringsbugg i `pricing.py` — watch_date:s egen månad felklassades som icke-FOMC så fort ett mötesdatum inom den passerats, vilket gav falska diskontinuiteter kring varje FOMC-beslut och månadsskifte (hittat via Modul 6-jämförelsen mot Polymarket, se den raden). Ett tidigare "FRED-ankare" för att lösa watch-månadens Pstart är helt borttaget till förmån för att bakåtlösningen nu även täcker fönstrets första månad. |
| 4. Validering mot CME | ✅ Klar | `fedwatch/validation/`. `Data/FedMeeting_*.csv` (CME:s egna historiska sannolikheter, ~1 års historik, 12 möten, 80 107 datapunkter) driver ett riktigt automatiskt jämförelsetest. **12/12 möten ≥99.5% av datapunkterna inom ±2pp**, medelavvikelse 0.01–0.07pp per möte — se `fedwatch/validation/README.md` för en verklig prispropageringsbugg som hittades och fixades 2026-07-15 (se Modul 3-raden nedan), vilket förbättrade dessa siffror 5-6x från en tidigare version (10/12 möten, upp till 21pp fel). cmegroup.com blockerar fortfarande programmatisk åtkomst (403) — historiken kom via manuell export. |
| 5. Polymarket-integration | ✅ Klar | `fedwatch/polymarket/`. clob.polymarket.com + gamma-api.polymarket.com är fritt tillgängliga. Bygger en KANDIDATTABELL (`config/polymarket_fomc_match_review.csv`) som måste granskas för hand (kolumn `confirmed`) innan Modul 6 använder den — 24 rader kvar efter användarens granskning (2 dubbletter borttagna). |
| 6. Jämförelse & output | ✅ Klar | `fedwatch/comparison/`. Jämför FedFunds-motorns lokala stegfördelning mot Polymarkets priser. **Riktig bugg hittad via denna jämförelse (2026-07-15):** användaren observerade en konstig sannolikhetsdipp i januari 2025/2026-panelerna i en genererad artefakt — spårades till att `build_month_frame` felklassificerade watch_date:s egen kalendermånad som icke-FOMC så fort ett mötesdatum inom månaden passerats, vilket lät den månadens råa pris framåtpropageras in i NÄSTA månads Pstart. Fixad i `fedwatch/deconvolution/pricing.py` (se docstring där + 2 nya regressionstester). Separat, kvarstående och MEDVETET ej fixat fynd: vår `local`-fördelning är alltid exakt binär (två utfall) medan Polymarket prisar in fler — det är CME:s egen metodbegränsning synlig i riktig data, inte en bugg (breddning provades tidigare och gav sämre träffsäkerhet mot CME:s riktiga siffror) — se motivering i `compare.py`. |
| 7. Live-notiser (Telegram) | ✅ Klar | `fedwatch/notify/`, `fedwatch/livesource/`. Kör `run_notify.py` dagligen (lokalt eller via `.github/workflows/notify.yml`) och skickar en Telegram-notis när ett FOMC-mötes ledande utfallsnivå uppfyller entry-regeln i `STRATEGY.md` §4. **Datakälla för p är investing.com/central-banks/fed-rate-monitor, INTE ZQ-kontraktspipelinen** — cmegroup.com:s eget FedWatch-verktyg är skyddat av Akamai bot management (403, ingen väg runt utan detection-evasion-teknik vi valt att inte bygga), medan investing.com visar samma typ av tabell utan bot-skydd (verifierat 2026-07-16). Se `fedwatch/livesource/investing.py` för hur den kumulativa tabellen konverteras till samma lokala stegfördelning som `engine.py` producerar. Se sektionen "Live-notiser" nedan för uppsättning. |

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

59 tester, ingen nätverksåtkomst krävs (Modul 3/4-testerna använder de
CSV-fixturer som redan ligger i `config/`/`Data/`; Modul 7:s tester kör mot
en sparad kopia av investing.com-sidan i `tests/fixtures/`).

**OBS:** `Data/` (rå ZQ-kontraktsdata + CME:s historiska export) är
gitignored i det publika repot av licensskäl — Modul 3/4:s tester
(`test_deconvolution.py`) kräver den mappen lokalt för att gå igenom. Se
`fedwatch/ingestion/README.md`/spec:en för var kontraktsdatan kommer ifrån
om du klonar repot och vill köra hela pipelinen själv.

## Live-notiser (Modul 7)

`run_notify.py` kollar dagligen om något FOMC-mötes ledande utfallsnivå
kvalificerar för entry enligt `STRATEGY.md` §4, och skickar en Telegram-notis
om så är fallet. Detta är forskning, inte en rekommendation — läs
`STRATEGY.md` §9 (kända begränsningar) innan du agerar på en notis.

**Skaffa en Telegram-bot:**
1. Prata med [@BotFather](https://t.me/BotFather) på Telegram, kör `/newbot`
   och följ instruktionerna — du får en bot-token.
2. Skicka ett valfritt meddelande till din nya bot, besök sedan
   `https://api.telegram.org/bot<DIN_TOKEN>/getUpdates` i en webbläsare och
   leta upp `"chat":{"id": ...}` — det är ditt `chat_id`.

**Köra lokalt:**
```bash
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
python run_notify.py
```

**Köra via GitHub Actions (schemalagt):** lägg `TELEGRAM_BOT_TOKEN` och
`TELEGRAM_CHAT_ID` som repo-secrets (Settings → Secrets and variables →
Actions) — workflowen i `.github/workflows/notify.yml` körs sedan
automatiskt dagligen. Den behöver INTE `Data/` (investing.com-källan gör
programanrop över nätet, inga lokala kontraktsfiler).

Valfria miljövariabler: `NOTIFY_THRESHOLD_PCT` (default 60.0, tröskeln T i
STRATEGY.md §4) och `NOTIFY_WINDOW_DAYS` (default 90).

## Miljö

Paket installeras i den delade venv:n `main` (inget separat virtualenv för
detta projekt — beslutat med användaren). Se `requirements.txt`.
