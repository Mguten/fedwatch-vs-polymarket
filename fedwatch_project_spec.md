# Projektspecifikation: Egen FedWatch-replikering + Polymarket-jämförelse

## Övergripande mål
Bygg en pipeline som:
1. Läser rå Fed Funds futures-priser (ZQ-kontrakt) från lokala CSV-filer
2. Extraherar marknadsimplicita sannolikheter per FOMC-möte, enligt CME:s FedWatch-metodologi
3. Validerar resultatet mot CME:s egna publicerade historiska sannolikhetsdata
4. Hämtar motsvarande Polymarket-data och jämför sannolikhetsfördelningarna över tid

Referens för metodologin: https://www.cmegroup.com/articles/2023/understanding-the-cme-group-fedwatch-tool-methodology.html
Referensimplementation att jämföra logik mot: `pyfedwatch` (Python-paket på GitHub/PyPI)

---

## Modul 1: Data Ingestion (ZQ-kontrakt)

**Källa:** Lokala CSV-filer i mappen `Data/`, en fil per kontraktsmånad, namngivna `ZQ<månadskod><år>.csv` (t.ex. `ZQF22.csv`, `ZQM26.csv`).

**Kolumnstruktur (bekräftad):**
```
Symbol: ZQ<X><YY>
Date Time | Open | High | Low | Close | Change | Volume | Open Interest
```

**Krav:**
- Läs in samtliga filer i `Data/` automatiskt (glob-mönster `ZQ*.csv`), inget hårdkodat filnamn.
- Parsa `<månadskod><år>` ur filnamnet till ett faktiskt kontraktsmånad/år (använd samma F/G/H/J/K/M/N/Q/U/V/X/Z-mappning vi redan definierat).
- **Filtrera bort lågkvalitetsdatapunkter:** rader med `Volume == 0` OCH `Open Interest` under en konfigurerbar tröskel ska flaggas som opålitliga (inte nödvändigtvis raderas — behåll som separat "low_confidence"-flagga i output, så vi kan välja att exkludera dem i efterhand utan att förlora data).
- Output: en enhetlig DataFrame med kolumner `contract_symbol, contract_month, contract_year, date, close_price, volume, open_interest, low_confidence_flag`.

---

## Modul 2: FOMC-mötesdatum (dynamisk hämtning)

**Krav:**
- Hämta FOMC-mötesschema dynamiskt, primärt från Federal Reserves egen kalendersida (federalreserve.gov/monetarypolicy/fomccalendars.htm) eller annan pålitlig, fritt tillgänglig källa.
- **Fallback:** om skrapning misslyckas (sidan ändrar struktur, blockerar bots, etc.), fall tillbaka till en manuellt underhållen statisk lista i en separat, lätt redigerbar fil (`fomc_dates.csv` eller liknande) — bygg inte en pipeline som helt kraschar om skrapningen failar.
- Varje möte ska sparas med: startdatum, slutdatum (möten är ofta två dagar), och vilket beslut som faktiskt togs (för validering i efterhand — detta behövs för Modul 5).

---

## Modul 3: Deconvolution Engine — FULLT MULTI-STEG

**Detta är kärnan. Granularitet: fullt multi-steg (flera bp-nivåer), inte binärt/ternärt.**

**Krav enligt CME:s metodologi:**
1. Beräkna väntevärdet av genomsnittlig ränta per kontraktsmånad: `E[R̄]_i = 100 - close_price_i`.
2. Klassificera varje kontraktsmånad som FOMC-månad eller icke-FOMC-månad.
3. **Icke-FOMC-månader:** implementera CME:s propageringsregel exakt — propagera implicit ränta framåt endast en månad, bakåt så många månader som behövs, för att minimera diskontinuiteter i räntebanan (se metodologisidan för exakt ordning).
4. **FOMC-månader:** implementera "heltal + mantissa"-nedbrytningen (steg 6-7 i CME:s dokument) för att räkna ut förväntat antal 25bp-steg, och generalisera **korrekt** till fler än två utfall när mantissan/spridningen indikerar att sannolikhetsmassan sannolikt sprids över fler än två närliggande nivåer (t.ex. vid långt tidsavstånd till mötet). Detta var precis den svaghet vi identifierade i CME:s egen förenkling — bygg in en flagga i output som visar när modellen approximerar med bara två utfall vs. när den använder fler.
5. Hantera möten där kontraktsmånaden innehåller mer än ett FOMC-möte (spread mellan på varandra följande kontrakt krävs — se tidigare diskussion i projektet).

**Output:** för varje FOMC-möte, en sannolikhetsfördelning över möjliga utfall i 25bp-steg (t.ex. -50bp: 5%, -25bp: 20%, 0bp: 60%, +25bp: 15%), plus en confidence-flagga (se punkt 4).

---

## Modul 4: Validering mot CME FedWatch

**Krav:**
- Ladda ner CME:s egna historiska sannolikhets-Excel-filer (gratis, ca 1 års historik bakåt, hittade tidigare i projektet via FedWatch-verktygets "Historical"-flik).
- Kör din egen motor på samma datum som CME:s exportfiler täcker.
- Bygg ett automatiskt jämförelsetest: för varje datum och möte, jämför din sannolikhetsfördelning mot CME:s, rapportera absolut avvikelse per utfallsnivå.
- **Definiera en tolerans innan du kör testet** (t.ex. ±2 procentenheter), inte efteråt utifrån vad som "ser bra ut".
- Om avvikelsen konsekvent är stor för vissa månader (t.ex. multi-möte-månader), flagga det som ett känt metodgap snarare än att dölja det.

---

## Modul 5: Polymarket-integration

**Datahämtning:**
- Kolla om `clob.polymarket.com`-API:et är fritt tillgängligt för historisk data utan nyckel/kostnad. Om ja: bygg direktanrop.
- Om API:et kräver betalning eller är kraftigt rate-limitat: fall tillbaka till CSV-export (manuell nedladdning, samma mönster som ZQ-datan).

**Marknadsmatchning (ANTAGANDE — bekräfta eller korrigera):**
- Polymarket-marknader är frågebaserade ("Will the Fed raise rates in July 2026?"), inte ticker-baserade som ZQ. Anta att Claude Code behöver:
  1. Hämta listan över alla Fed-relaterade marknader via API/sökning på nyckelord ("Fed", "FOMC", "interest rate").
  2. Matcha varje marknads upplösningsdatum mot närmaste FOMC-mötesdatum (från Modul 2).
  3. Bygg en manuell verifieringstabell (marknads-ID → matchat FOMC-möte) som **du granskar för hand** innan den används i produktion — automatisk textmatchning på frågeformuleringar är felbenäget och du vill inte upptäcka en felmatchning efter att hela jämförelsen är klar.

---

## Modul 6: Jämförelse & output

- Tidsserie av `P_FedFunds(möte, datum)` vs `P_Polymarket(möte, datum)` för varje matchat möte.
- Beräkna och spara skillnaden som egen tidsserie.
- Lämna plats för framtida analys (korrelation mot volatilitetsproxy, CPI-datum) men bygg inte den analysen i detta steg — scope för nu är att få jämförelsedatan på plats, inte att dra slutsatser.

---

## Tekniska riktlinjer till Claude Code

- Python, pandas för datahantering.
- Modulär kod: en fil/modul per steg ovan, inte en monolitisk skript-fil — du kommer vilja testa och validera varje modul isolerat (se tidigare diskussion om varför).
- Skriv enhetstester för Modul 3 (avkonvolveringslogiken) mot minst 2-3 kända CME FedWatch-datapunkter innan resten av pipelinen byggs vidare.
- Logga tydligt när low_confidence-data används i en beräkning, så du kan spåra om ett konstigt resultat beror på datakvalitet.
