import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sesklon-test-"))
os.environ["PRELOAD"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
