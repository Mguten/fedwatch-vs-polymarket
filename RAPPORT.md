# Att replikera CME FedWatch och hitta mispricing i Polymarket

*Utkast till rapport — [ditt namn], [datum]. Se kommentaren längst ner om vad
som bör dubbelkollas innan publicering.*

## 1. Bakgrund och syfte

CME:s FedWatch-verktyg omvandlar priser på Fed funds-terminer (ZQ-kontrakt)
till marknadsimplicerade sannolikheter för Federal Reserves räntebeslut.
Metoden är offentligt beskriven men inte öppen källkod, och terminspriserna
är fritt tillgängliga — det gjorde den till ett bra projekt för att testa om
jag kunde replikera en verklig, marknadsanvänd prissättningsmodell från grunden
och sedan använda den för något CME själva inte gör: jämföra den mot en
oberoende marknad som prissätter exakt samma händelser.

Den marknaden är Polymarket, där FOMC-möten handlas som separata
prediction-markets per utfall (t.ex. "sänker Fed med 25bp i september?").
Två marknader som prissätter samma verklighet men med olika deltagare,
likviditet och uppdateringsfrekvens är ett naturligt ställe att leta efter
mätbara skillnader i hur snabbt och hur väl information prisas in.

Målet med det här projektet var tredelat:

1. Bygg en motor som replikerar CME:s metodik från rådata (terminspriser,
   mötesdatum, målräntor) och validera den mot CME:s egna publicerade
   sannolikhetstabeller.
2. Jämför motorns output mot Polymarkets priser över tid.
3. Undersök om skillnaden — om det finns någon — går att omsätta i en
   handelsstrategi, och testa den ansatsen med samma skepticism jag skulle
   ha mot vilken "för bra för att vara sant"-signal som helst.

## 2. Metod i korthet

- **Data:** CME Fed funds-terminers slutkurser per kontraktsmånad, FOMC-
  mötesdatum (federalreserve.gov), målräntehistorik (FRED), samt Polymarkets
  historiska prisdata (gamma- och CLOB-API).
- **Prissättning:** CME:s metod bryter ner varje kontraktsmånads
  förväntade ränta i en heltals- och mantissdel, fördelar mantissan binärt
  över möjliga 25bp-steg för det närmaste mötet, och konvolverar den
  fördelningen framåt genom hela mötessekvensen för att få fram
  sannolikheter för senare möten.
- **Validering:** Modellens output jämfördes bin-för-bin mot CME:s egna
  publicerade sannolikhetstabeller för 12 historiska datum.

## 3. Felsökningsresan — den viktigaste delen av projektet

Den mest lärorika delen av arbetet var inte att bygga modellen, utan att
hitta ett fel i den efter att den redan "fungerade".

När jag plottade modellens output mot Polymarkets priser över tid såg jag en
tydlig, återkommande svacka i modellens sannolikheter kring januari 2025 och
januari 2026 — en dipp som inte hade någon rimlig motsvarighet i
terminsmarknaden. Att jaga ner orsaken visade sig avslöja ett strukturellt
fel i hur motorn klassificerade månader:

- Motorn avgjorde om en kalendermånad skulle behandlas som en "FOMC-månad"
  baserat på en lista av möten som redan hade filtrerats mot dagens datum.
  Så fort ett möte hade *ägt rum* tidigare i samma månad — men innan
  månaden var slut — föll den månaden ur listan och klassades felaktigt som
  en icke-FOMC-månad.
- Effekten: månadens opriser genomsnitt (inte den korrekt uppdelade
  sannolikhetsfördelningen) fortplantades rakt in i nästa månads
  startvärde, vilket skapade ett hopp i modellens output exakt vid
  månadsskiften efter ett möte.
- Ett besläktat fel fanns i en "ankarmekanism" jag hade byggt in för att
  hantera fall med två möten i följd utan mellanliggande månad — den
  ersatte en månads egna prissatta förväntan med dagens punktränta, vilket
  skapade samma typ av diskontinuitet vid varje månadsgräns.

Fixen var att ge motorn hela den ofiltrerade möteslistan (så
klassificeringen inte beror på vilket datum man frågar från) och att ta
bort ankarmekanismen helt till förmån för att låta varje månad — inklusive
den första — lösas mot sitt eget prissatta genomsnitt precis som alla andra
FOMC-månader.

Resultatet av fixen, mätt mot CME:s egna historiska tabeller: andelen möten
inom ±2 procentenheters tolerans gick från **10 av 12 till 12 av 12**, och
den genomsnittliga avvikelsen föll **5–6 gånger**. Bugen hade alltså inte
bara gett en missvisande graf — den hade dolt en betydande del av modellens
verkliga precision.

Lärdomen jag tar med mig: en modell som "ser rimlig ut" och en modell som är
*validerad mot en oberoende sanning* är inte samma sak, och avvikelser som
är lätta att avfärda som brus är ofta värda att jaga ner.

## 4. Är modellen eller Polymarket bättre kalibrerad?

Med motorn validerad kunde jag jämföra dess sannolikheter mot Polymarkets
priser för samma möten, med Brier score som mått (lägre är bättre
kalibrerat — dvs. sannolikheterna stämmer bättre överens med det faktiska
utfallet).

Inom ett fönster av **90 dagar före respektive möte** (ett intervall jag
valde efter att separat ha undersökt hur volatiliteten i råpriserna växer
ju längre bort från mötet man mäter):

- Modellen hade lägre (bättre) Brier score i **15 av 19** avgjorda möten
  (2023–2026), cirka 79 %.
- Genomsnittlig Brier score: **≈0,037 för modellen mot ≈0,045 för
  Polymarket** — en förbättring på cirka 18 %.
- De möten där Polymarket var bättre kalibrerat (bl.a. 2024-07-31,
  2025-06-18) var inte koncentrerade till någon uppenbar gemensam orsak —
  värt att notera som en ärlig begränsning snarare än att bara visa upp
  vinstsidan.

En naturlig följdfråga: beror det på att modellen "vet svaret" tidigare än
Polymarket? Svaret var **nej** — jag hittade inget systematiskt tidsledande
mönster där modellens sannolikheter blev säkra före Polymarkets priser.
Istället visade sig edgen komma från något mer specifikt: modellen tenderar
att flagga ett utfall som sin ledande gissning *innan Polymarkets pris hunnit
i kapp fullt ut*, vilket i praktiken ger billigare genomsnittligt
inköpspris för motsvarande position — **57 öre mot 70 öre** i backtesten.

## 5. Kontrollexperimentet — en läxa i statistisk skepticism

Den första versionen av en handelsstrategi byggd på detta (köp när modellen
är säker, sälj vid övertagning eller mötets avgörande) gav ett resultat som
var för bra: samtliga testade möten resulterade i positiv utgång.

Istället för att ta det som ett facit körde jag ett kontrollexperiment: vad
händer om man byter ut modellens signal mot **Polymarkets eget pris** som
identisk regel? Om kontrollen presterar lika bra, säger resultatet inget om
modellens unika värde — det säger bara att FOMC-besluten under perioden i
stort sett var väl telegraferade i förväg.

Det var precis vad som hände. Kontrollen träffade nästan lika bra som
modellen. Slutsatsen: den perfekta träffsäkerheten var inte bevis på
modellskicklighet, utan en egenskap hos perioden som studerades.

Det jag gjorde härnäst är den del jag är mest nöjd med: snarare än att
skrota resultatet letade jag efter en *mindre men mekanistiskt förklarad*
edge som överlevde kontrollen — och hittade den i skillnaden i
genomsnittligt inköpspris (avsnitt 4). Den edgen är svagare än den första,
för bra-för-att-vara-sann siffran, men den har en konkret förklaring och
klarade ett test specifikt utformat för att slå hål på den.

## 6. Strategin i korthet

Reglerna är formaliserade i ett separat dokument (se `STRATEGY.md` i
projektet); i sammanfattning:

- **Instrument:** enskilda utfallsnivåer på Polymarkets kanoniska
  FOMC-mötesmarknader, inom 90-dagarsfönstret.
- **Entry:** modellens sannolikhet p över en konfigurerbar tröskel T,
  *och* p > Polymarkets pris (positiv edge — ett villkor som krävs för att
  Kelly-baserad positionsstorlek ska vara meningsfull).
- **Exit:** när en annan nivå tar över som modellens ledande gissning,
  eller när mötet avgörs.
- **Storlek:** Kelly-fraktion f\* = (p−P)/(1−P), i praktiken fraktionerad
  (¼–½×) med ett hårt tak per position — fullt Kelly gav i snitt 40,6 % av
  bankrullen per trade och upp till 100 % i enskilda fall, vilket är för
  aggressivt för att använda orört.

| Tröskel T | Trades | Möten med negativ PnL | Snitt PnL/möte | Hit rate |
|---|---|---|---|---|
| 50 % | 44 | 0/19 | +0,52 kr | 84,1 % |
| 60 % | 34 | 0/19 | +0,48 kr | 85,3 % |
| 70 % | 30 | 0/19 | +0,40 kr | 86,7 % |

Ett enskilt möte (september 2024, ett mer genuint överraskande beslut än
resten av perioden) bidrog med ungefär 11 % av den totala backtest-PnL:n —
tillräckligt lite för att resultatet inte ska tolkas som beroende av en
enda outlier.

## 7. Kända begränsningar

Det här avsnittet är medvetet lika framträdande som resultaten:

- **n=19 avgjorda möten, inte 30–44 oberoende observationer.** Flera trades
  inom samma möte är korrelerade eftersom de delar utfall — den statistiska
  styrkan är svagare än antalet trades antyder.
- **En enda historisk regim** (2023–2026, en välkommunicerad
  höjnings-till-sänkningscykel). Perioder med fler genuina överraskningar
  skulle kunna se annorlunda ut.
- **Inga transaktionskostnader modellerade** — verklig spread och
  slippage vid faktisk orderläggning kan vara sämre än det observerade
  priset.
- **Ingen bekräftad kausal förklaring** — den mekaniska hypotesen (avsnitt
  4–5) är stödd av ett kontrollexperiment, inte bevisad som en stabil,
  bestående marknadsineffektivitet.
- **Ingen out-of-sample-validering.** Alla siffror ovan kommer från samma
  period som användes för att formulera strategin.

## 8. Slutsats

Det här projektet var inte i första hand en jakt på en handelsstrategi —
det var en övning i att bygga en kvantitativ pipeline från rådata till en
verklig marknadsjämförelse, validera den mot en oberoende sanning, hitta
och fixa ett fel som annars hade förblivit dolt, och sedan utvärdera ett
lovande resultat med samma skepticism jag skulle vilja att någon annan
använde mot mina egna påståenden. Edgen som återstår efter kontrollen är
liten och inte bevisat varaktig — men processen för att komma fram till den
är, tror jag, den delen som faktiskt visar hur jag tänker kring finansiella
data.

## 9. Disclaimer

Detta är forskning i utbildnings- och portföljsyfte, inte
investeringsrådgivning. Historisk backtestprestanda garanterar inte
framtida resultat, i synnerhet inte för en strategi validerad på ett enda,
litet, korrelerat dataset.

---

**Att göra innan publicering:** siffrorna ovan är hämtade från tidigare
interaktiva beräkningar i det här projektet (delvis från filer i en
temporär scratchpad-katalog som inte är del av det versionerade projektet).
Kör om de underliggande skripten mot `output/`-filerna och stäm av varje
siffra i rapporten mot färsk output innan den går live — särskilt
Brier-score-genomsnitten i avsnitt 4 och backtesttabellen i avsnitt 6.
