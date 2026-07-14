# Modul 4: Validering mot CME FedWatch

## Status: klar (2026-07-14)

`Data/FedMeeting_<YYYYMMDD>.csv` (en fil per möte, dagliga sannolikheter
över 25bp-band, ~1 års historik) och `Data/FedMeetingHistory_20260714.csv`
(samma data konsoliderad) lades till manuellt av användaren. Detta är
CME:s egna historiska sannolikhets-exports enligt spec — `fedwatch/validation/`
läser dem (`cme_history.py`) och kör det automatiska jämförelsetestet
(`validate.py`) mot Modul 3:s motor.

Kör via `python run_pipeline.py` (Modul 4-steget), eller direkt:

```python
from fedwatch.ingestion import load_all_contracts
from fedwatch.fomc.dates import get_fomc_meetings
from fedwatch.validation import load_all_cme_meeting_histories, validate_against_cme

contracts = load_all_contracts()
meetings = get_fomc_meetings()
cme_history = load_all_cme_meeting_histories()
result = validate_against_cme(cme_history, meetings, contracts)
print(result["per_meeting_summary"])
```

## Resultat (senast körd 2026-07-14, 80 107 datapunkter, 12 möten, 2025-07-14–2026-07-13)

| Möte | Datapunkter | Medelavvikelse (pp) | Maxavvikelse (pp) | Andel inom ±2pp |
|---|---|---|---|---|
| 2026-03-18 | 5 141 | 0.39 | 21.4 | 93.9% |
| 2026-04-29 | 6 618 | 0.31 | 16.8 | 94.6% |
| 2026-06-17 | 8 278 | 0.23 | 9.9 | 96.4% |
| 2026-07-29 | 9 915 | 0.18 | 8.9 | 97.2% |
| 2026-09-16 | 10 502 | 0.15 | 7.6 | 97.8% |
| 2026-10-28 | 9 444 | 0.12 | 7.1 | 98.2% |
| 2026-12-09 | 8 454 | 0.09 | 6.1 | 98.6% |
| 2027-01-27 | 7 410 | 0.09 | 5.9 | 98.4% |
| 2027-03-17 | 6 055 | 0.05 | 5.3 | 99.4% |
| 2027-04-28 | 4 410 | 0.05 | 5.3 | 99.3% |
| 2027-06-09 | 2 920 | 0.02 | 0.7 | 100.0% |
| 2027-07-28 | 960 | 0.02 | 0.6 | 100.0% |

0 (möte, datum)-par kunde inte beräknas alls (jämfört med tidigare, innan
Sep–Dec-kontraktsdatan lades till, då 6 möten helt saknade prisdata).

## Känt metodgap: december 2025

De två möten som hamnar under 95%-tröskeln (2026-03-18, 2026-04-29) gör det
inte jämnt utspritt — de värsta avvikelserna (15-21pp) klustrar nästan
uteslutande kring **11–31 december 2025**, dvs. precis runt/efter det
faktiska FOMC-mötet 2025-12-09/10 (en verklig 25bp-sänkning, se
`config/fomc_dates.csv`/Modul 2). Utanför det fönstret är avvikelsen för
båda mötena i linje med övriga (<1pp).

Mest sannolika förklaring (inte fullt rotorsaksbestämd — flaggas hellre än
göms, per spec): en baslinje-/tajmingeffekt kring själva beslutsdatumet,
t.ex. hur FRED:s DFEDTARU/DFEDTARL-serie (som Modul 3 använder som
ankarränta) uppdaterar sig relativt CME:s egen konvention för när en ny
target-rate "gäller" i sannolikhetsberäkningen. Detta drabbar bara möten
som ligger LÅNGT nog fram (mars/april 2026) att decembermötet 2025 är en
mellanliggande, redan avklarad, länk i konvolveringskedjan — inte
decembermötet självt eller närliggande möten.

Detta är exakt den typ av "konsekvent avvikelse för vissa månader" spec
ber oss flagga som ett känt metodgap snarare än att dölja. Vidare
felsökning (exakt vilken dag FRED:s serie skiftar relativt CME:s egen
brytpunkt) är inte gjord — tidsboxat för att inte spendera obegränsad tid
på ett smalt, redan litet (<0.4pp i snitt) gap.

## Om cmegroup.com fortfarande är blockerat

`curl` mot `cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html` gav
403 (även med browser-UA) när detta testades — den historiska datan ovan
kom via manuell export av användaren, inte programmatisk hämtning. Se
`fedwatch/validation/cme_history.py` för inläsningslogiken om fler
historik-exports läggs till senare (bara droppa fler
`FedMeeting_<YYYYMMDD>.csv`-filer i `Data/`, ingen kodändring behövs).
