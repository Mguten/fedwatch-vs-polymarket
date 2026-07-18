# Handelsstrategi: FedFunds-motorn som signal mot Polymarket

Formaliserar den strategi som backtestats interaktivt i projektets research-arbete
(se konversationshistorik / `output/`). Detta är ett **regeldokument**, inte en
implementation — inget i `fedwatch/`-paketet kör den här strategin automatiskt.

## 1. Syfte

Handla enskilda utfallsnivåer ("buckets", t.ex. "-25bp") på Polymarkets
FOMC-mötesmarknader, med FedFunds-motorns `local`-sannolikhet som
fair-value-signal. Bygger på tre research-fynd:

1. Vår motor är bättre kalibrerad än Polymarket nära ett möte (lägre
   Brier-score inom ett 90-dagarsfönster).
2. **Reviderat 2026-07-17:** vår motor visar ett litet men mätbart
   tidsförsprång framför Polymarket — median ~0,5–3,5 dagar beroende på
   vilken sannolikhetströskel man mäter mot, bekräftat via två oberoende
   metoder (tröskelpassering vid flera nivåer + korsvis korrelation med
   toppvärde vid +2 dagars förskjutning). Detta ersätter en tidigare
   slutsats ("blir inte nödvändigtvis säker TIDIGARE") som byggde på
   motorn FÖRE dagräkningsfixen samma dag — den buggen adderade brus i
   just tidsdimensionen och maskerade sannolikt ett förspång som redan
   fanns.
3. Detta tidsförsprång är sannolikt själva MEKANISMEN bakom edgen: eftersom
   vår motor tenderar att flagga en nivå som sin ledande gissning INNAN
   Polymarkets pris hunnit i kapp, kan vi köpa billigare (snitt 57 öre mot
   70 öre för motsvarande position, se kontrollexperimentet i
   konversationshistoriken).

## 2. Instrument och urval

- **Endast** event i den granskade matchningstabellen
  (`config/polymarket_fomc_match_review.csv`, `confirmed=TRUE`) — dvs. de
  kanoniska "Fed Decision in `<månad>`?"/"Fed Interest Rates: `<månad>`
  `<år>`?"-marknaderna, aldrig dissent-/bingo-/ordräkningsmarknader.
- En **nivå** (bucket, t.ex. "-25bp") är handelsbar bara om den finns
  **både** i vår motors `local`-fördelning (Modul 3, `row_type='local'`)
  **och** som en egen submarknad på Polymarket för samma möte
  (`fedwatch/polymarket/history.py`).
- **Tidsfönster: högst 90 dagar före mötet.** Motiveras av
  volatilitetsutforskningen — bortom det växer bruset i råpriserna
  snabbare än likviditeten motiverar (se separat analys). Signaler utanför
  fönstret ignoreras helt, även om de ser starka ut.

## 3. Signal

Låt för en given (möte, nivå, dag):

- **p** = vår motors sannolikhet för den nivån (`fedfunds_probability_pct`/100)
- **P** = Polymarkets pris för YES på den nivån (`polymarket_probability_pct`/100)
- **edge** = p − P

Den **ledande nivån** en given dag = den nivå (bland de handelsbara) som har
högst p den dagen.

## 4. Entry-regel

Gå in i en position (köp YES på den ledande nivån) när **båda** villkoren
uppfylls samma dag:

1. **p ≥ T** (konfidenströskel — se §8 för referensvärden; inget värde är
   låst som "det officiella", välj T medvetet per körning)
2. **p > P** (positiv edge — utan detta krav blir Kelly-formeln i §6
   meningslös, och 5 av 45 signaler i den ursprungliga backtesten saknade
   den här egenskapen)

Endast **en position per möte åt gången**. Flera möten kan ha öppna
positioner samtidigt (oberoende kontrakt) — det finns ingen begränsning
mot det.

## 5. Exit-regler

Positionen stängs vid det FÖRSTA av:

- **(a) Övertagen.** En annan nivå blir ny ledare (högre p) samma dag.
  Sälj hela positionen till dagens Polymarket-pris för den nivå du
  redan äger. Om den nya ledaren i sin tur uppfyller entry-villkoren i §4,
  öppna omedelbart en ny position i den — annars stå utan position tills
  nästa kvalificerande signal.
- **(b) Mötet avgörs.** Ingen övertagning har skett — håll till
  upplösning. Utbetalning = 1 om nivån var det faktiska utfallet, annars 0.

## 6. Positionsstorlek — Kelly

Kelly-fraktion för att köpa en YES-andel till pris P när du tror den sanna
sannolikheten är p:

```
f* = (p − P) / (1 − P)
```

(Härledning: satsar du 1 kr köper du 1/P andelar; vinner du får du 1/P kr
(profit 1/P−1, "odds" b=(1−P)/P); Kelly f*=(bp−(1−p))/b förenklas till
ovanstående.)

**I backtesten (T=60%, edge-krav, 90-dagarsfönster) var full-Kelly-fraktionen
i snitt 40,6% av bankrullen per trade, med max 100% på en enskild trade.**
Det är för aggressivt att använda rakt av:

- **Rekommendation: fraktionerad Kelly (t.ex. ¼–½ × f\*).** Standardpraxis
  för att kompensera för att p är en MODELLSKATTNING, inte en känd sanning
  — full Kelly är extremt känslig för skattningsfel i p, och vår modell
  har validerats på ett enda historiskt fönster (se §9).
- **Rekommendation: hårt tak per enskild trade** (t.ex. 10% av bankrullen)
  oavsett vad Kelly-formeln säger, just för att undvika 100%-fallen som
  förekom i backtesten.
- Dessa två rekommendationer är INTE backtestade i sig — de är etablerad
  riskpraxis, inte en verifierad regel från vår data. Full-Kelly-siffrorna
  ovan är de enda Kelly-relaterade talen som faktiskt är beräknade från
  historiken.

## 7. Riskhantering (utöver Kelly-taket)

- Sätt ett tak för **total exponering samtidigt** över alla öppna
  positioner (t.ex. X% av bankrullen), inte bara per trade — flera möten
  kan vara öppna parallellt (§4).
- Ingen ytterligare stop-loss utöver §5(a) är definierad eller backtestad.
  Om du vill lägga till en hård stop-loss (t.ex. sälj om priset rör sig
  X pp emot dig även utan övertagning) är det en NY regel som bör
  backtestas separat innan den används.
- Exekvering antas ske till det pris `polymarket_probability_pct`
  representerar (senaste pris/mid). Verklig spread, orderdjup och
  slippage är INTE modellerat — se §9.

## 8. Backtest-referens (90-dagarsfönster, edge-krav, 19 avgjorda möten 2023–2026)

| Tröskel T | Antal trades | Möten med negativ total PnL | Snitt PnL/möte (1 kr insats) | Hit rate |
|---|---|---|---|---|
| 50% | 44 | 0/19 | +0,52 kr | 84,1% |
| 60% | 34 | 0/19 | +0,48 kr | 85,3% |
| 70% | 30 | 0/19 | +0,40 kr | 86,7% |

Lägre tröskel → fler, billigare, tidigare köp (mer av edgen från §1 punkt 3)
men något lägre hit rate per trade. Skillnaden mellan tröskelvärdena är
liten jämfört med osäkerheten i §9 — välj inte T baserat på skillnader i
andra decimalen här.

## 9. Kända begränsningar — läs innan du använder detta med riktiga pengar

- **n=19 avgjorda möten, inte n=30-44 oberoende observationer.** Flera
  trades inom samma möte är korrelerade (samma underliggande utfall).
  Den sanna statistiska styrkan i resultaten är svagare än trade-antalet
  antyder.
- **En enda historisk regim** (2023–2026, en väl kommunicerad
  höjnings-till-sänknings-cykel). Perioder med fler genuina överraskningar
  (jfr september 2024, se konversationen) skulle kunna se annorlunda ut —
  det mötet bidrog ändå bara ~11% av total backtest-PnL, så resultatet är
  inte helt beroende av det.
- **Inga transaktionskostnader modellerade.** Polymarket tar ut avgifter
  på vinst; verklig spread/slippage vid faktisk orderläggning kan vara
  sämre än det observerade priset, särskilt vid lägre likviditet.
- **Ingen bekräftad kausal förklaring.** Vi har en mekanisk hypotes
  (motorn flaggar konviktion innan Polymarkets pris hunnit i kapp) stödd
  av ett kontrollexperiment, men det är inte samma sak som ett bevisat,
  stabilt marknadsinefficiens som kommer bestå framåt.
- **Ingen out-of-sample-validering.** Alla siffror i §8 är från samma
  historiska period som användes för att formulera strategin. Inget är
  testat på data som inte redan sågs under research-fasen.
- **Detta är forskning, inte en rekommendation.** Läs detta dokument som
  en formaliserad hypotes att eventuellt testa vidare (paper trading,
  litet kapital, out-of-sample-period) — inte som en färdig, validerad
  handelsstrategi.

## 10. Definitioner

| Term | Betydelse |
|---|---|
| Nivå / bucket | Ett specifikt bp-utfall för ett möte, t.ex. "-25bp" (`bp_delta` i `output/fedfunds_vs_polymarket.csv`) |
| p | Vår motors `local`-sannolikhet för en nivå en given dag |
| P | Polymarkets pris (≈ marknadens implicita sannolikhet) för samma nivå/dag |
| Edge | p − P |
| Ledande nivå | Nivån med högst p bland de handelsbara nivåerna för mötet, en given dag |
| Övertagen | Att en annan nivå blir ny ledare — utlöser exit enligt §5(a) |
