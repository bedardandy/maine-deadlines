import datetime as dt
import sys
from pathlib import Path

# Make the package importable without installing (src layout).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

AS_OF = dt.date(2026, 7, 7)  # pinned so staleness never trips inside the suite
