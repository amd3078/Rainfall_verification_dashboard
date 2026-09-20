"""Make the repository root importable so tests can `import app`.

The verification functions currently live in `app.py` alongside the Streamlit
UI. Importing the module is headless-safe (the UI only runs under
`streamlit run`), so the scientific functions can be tested directly.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
