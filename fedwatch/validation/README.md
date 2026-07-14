# Modul 4: Validering mot CME FedWatch — PAUSAD

## Status

Modul 4 enligt spec (ladda ner CME:s historiska sannolikhets-Excel-filer,
~1 års historik, och köra ett automatiskt jämförelsetest med en tolerans på
±2 procentenheter) är **inte byggd**. Detta var ett medvetet beslut i
samråd med användaren (se projektets startdiskussion) för att inte blockera
Modul 1, 2, 3, 5 och 6.

## Varför

`cmegroup.com` blockerar programmatisk åtkomst till FedWatch-verktyget:

```
$ curl --http1.1 -A "Mozilla/5.0 ..." https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
HTTP 403
```

Verktyget är dessutom JavaScript-drivet (den historiska Excel-exporten
triggas via ett klick i webbläsaren, inte en enkel nedladdningslänk), så
även om bot-blockeringen kringgicks skulle en ren HTTP-klient sannolikt inte
kunna trigga exporten utan headless-browser-automatisering.

## Vad som FINNS på plats trots detta

Användaren delade en skärmdump ("Validation probabilities") med CME:s
publicerade ZQ-kurva och "Conditional Meeting Probabilities" för elva möten
(2026-07-29 till 2027-12-08), som extraherats till:

- `config/cme_validation_zq_curve.csv`
- `config/cme_validation_probabilities.csv`

Detta är EN engångssnapshot (inte ~1 års historik över många datum, som
spec:s fulla Modul 4 kräver), men den har använts för att **rigoröst
enhetstesta Modul 3:s algoritm** (se `tests/test_deconvolution.py`) — vår
motor reproducerar CME:s publicerade siffror inom ±0.6 procentenheter över
samtliga sju testbara möten, långt inom den ±2pp-tolerans
(`config.CME_VALIDATION_TOLERANCE_PP`) som spec kräver för Modul 4.

Det här täcker alltså **algoritmkorrekthet** men inte Modul 4:s fulla syfte
(systematisk validering över tid, för att upptäcka ev. drift eller
metodgap som bara syns över många datum/månader).

## Hur man låser upp Modul 4 på riktigt

Någon av:

1. **Manuell export**: logga in i FedWatch-verktyget i en vanlig webbläsare,
   gå till fliken "Historical", exportera Excel-filerna för önskat
   datumintervall, och släpp dem i `Data/cme_historical/` (skapa mappen).
   Bygg sedan `fedwatch/validation/load_cme_export.py` för att läsa in dem
   (openpyxl finns redan i requirements.txt för detta).
2. **Headless-browser-automatisering** (t.ex. Playwright) för att trigga
   exporten programmatiskt — mer robust men betydligt mer arbete, och
   känsligt för att cmegroup.com ändrar sin bot-detektion.
3. Fler manuella skärmdumpar/exports över tid (samma mönster som den vi
   redan har) — ger fler enskilda datapunkter men aldrig den sammanhängande
   tidsserie spec efterfrågar.

Kontakta användaren för prioritering innan något av ovanstående byggs.
