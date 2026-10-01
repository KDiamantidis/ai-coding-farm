# Puts the repo root on sys.path so tests can `import farm`.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
