import os
import tempfile
from pathlib import Path


TEST_DATABASE = Path(tempfile.gettempdir()) / f"fotomaniabot-tests-{os.getpid()}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DATABASE}")
