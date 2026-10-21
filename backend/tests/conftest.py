import os
import tempfile
from pathlib import Path

os.environ.setdefault("MAX_DATA_DIR", tempfile.mkdtemp(prefix="fotomaniabot-data-"))
TEST_DATABASE = Path(tempfile.gettempdir()) / f"fotomaniabot-tests-{os.getpid()}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DATABASE}")


from app.main import init_db  # noqa: E402

init_db()
