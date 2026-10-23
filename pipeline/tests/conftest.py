import pytest
import sys
from pathlib import Path

# Add project root to python path
root = Path(__file__).resolve().parent.parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
