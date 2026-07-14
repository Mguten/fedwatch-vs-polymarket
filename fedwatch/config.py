"""Delade konfigurationsvärden för fedwatch-pipelinen."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"

# Modul 1: rader med Volume == 0 OCH Open Interest under detta värde
# flaggas som low_confidence (men behålls i output).
DEFAULT_OI_LOW_CONFIDENCE_THRESHOLD = 1000

# Modul 3: bp-steg som Fed normalt rör sig i.
BP_STEP = 25

# Modul 4: tolerans för validering mot CME:s publicerade sannolikheter,
# i procentenheter. Måste sättas innan valideringstestet körs (se spec).
CME_VALIDATION_TOLERANCE_PP = 2.0
