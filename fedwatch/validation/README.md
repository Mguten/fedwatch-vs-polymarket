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

## Resultat (senast körd 2026-07-15, 80 107 datapunkter, 12 möten, 2025-07-14–2026-07-13)

| Möte | Datapunkter | Medelavvikelse (pp) | Maxavvikelse (pp) | Andel inom ±2pp |
|---|---|---|---|---|
| 2026-03-18 | 5 141 | 0.07 | 6.8 | 99.6% |
| 2026-04-29 | 6 618 | 0.05 | 5.4 | 99.6% |
| 2026-06-17 | 8 278 | 0.05 | 4.6 | 99.5% |
| 2026-07-29 | 9 915 | 0.04 | 4.2 | 99.6% |
| 2026-09-16 | 10 502 | 0.03 | 3.4 | 99.9% |
| 2026-10-28 | 9 444 | 0.03 | 2.9 | 99.9% |
| 2026-12-09 | 8 454 | 0.02 | 2.5 | 99.9% |
| 2027-01-27 | 7 410 | 0.01 | 1.8 | 100.0% |
| 2027-03-17 | 6 055 | 0.02 | 1.4 | 100.0% |
| 2027-04-28 | 4 410 | 0.01 | 1.2 | 100.0% |
| 2027-06-09 | 2 920 | 0.02 | 1.2 | 100.0% |
| 2027-07-28 | 960 | 0.02 | 0.8 | 100.0% |

**12/12 möten ≥99.5% inom ±2pp** (tidigare 10/12, se nedan). 0 (möte, datum)-par
kunde inte beräknas alls.

## Löst: propageringsbugg kring mötesdatum och månadsskiften (2026-07-15)

Tidigare version av denna tabell visade 2 möten under 95% (2026-03-18: 93.9%,
2026-04-29: 94.6%) med avvikelser upp mot 21pp, klustrade kring december
2025. Det var **inte** ett CME-metodgap utan en verklig bugg i
`fedwatch/deconvolution/pricing.py`, hittad genom att jämföra vår motor mot
Polymarket i Modul 6 (se `fedwatch/comparison/`) — användaren observerade en
konstig "dipp" i januari 2025/2026-panelerna, vilket ledde till felsökningen.

**Rotorsak:** `build_month_frame` klassificerade en kalendermånad som
FOMC-månad genom att slå upp möten i den REDAN watch_date-filtrerade
möteslistan. Så fort watch_date passerade ett mötesdatum inom samma månad
(dagen efter varje FOMC-beslut, fram till månadsskiftet) föll det mötet ur
filtret och månaden felklassades som icke-FOMC — vilket fick dess råa,
odelade månadsgenomsnitt framåtpropageras rakt in i NÄSTA månads Pstart
istället för att det mötet löstes mot sitt eget Pavg. Ett separat men
besläktat problem fanns i det syntetiska "FRED-ankaret" som användes när
watch_date:s egen månad hade ett kommande möte — det gav en likadan
diskontinuitet vid varje månadsskifte (dagens punkt-ränta istället för
månadens prissatta förväntan).

**Fixen:** `build_month_frame` tar nu emot den FULLA möteslistan (inte
förfiltrerad) för månadsklassificering, och `propagate_prices` bakåtlöser
numera även den FÖRSTA månaden i fönstret (watch_date:s egen månad) mot dess
EGET Pavg + nästa månads Pend — precis som alla andra FOMC-månader i en
kedja. Ankar-mekanismen är helt borttagen. Se regressionstesterna
`test_index_zero_fomc_month_resolves_via_backward_solve_not_anchor` och
`test_month_classification_survives_a_past_meeting_in_watch_month` i
`tests/test_deconvolution.py`.

**Effekt:** medelavvikelsen föll 5-6x för samtliga möten (inte bara de två
tidigare flaggade), och taket för max-avvikelse föll från 21.4pp till 6.8pp.
Detta var alltså en generell förbättring av motorns korrekthet, inte en
punktinsats för december 2025 specifikt.

## Om cmegroup.com fortfarande är blockerat

`curl` mot `cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html` gav
403 (även med browser-UA) när detta testades — den historiska datan ovan
kom via manuell export av användaren, inte programmatisk hämtning. Se
`fedwatch/validation/cme_history.py` för inläsningslogiken om fler
historik-exports läggs till senare (bara droppa fler
`FedMeeting_<YYYYMMDD>.csv`-filer i `Data/`, ingen kodändring behövs).
