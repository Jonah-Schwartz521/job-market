"""Single source of truth for the database path.

Every entry point resolves the database here so that pointing the whole
project at a different file is one environment variable, not four edits:

    JOBS_DB=jobs.prod.db streamlit run app/dashboard.py
    JOBS_DB=jobs.prod.db python -m src.fetch.run

Unset, this is data/jobs.db. The path stays relative to the working
directory, unchanged from when it was hardcoded, so every caller still
expects to be run from the repo root.
"""

import os
from pathlib import Path

DEFAULT_DB = "data/jobs.db"


def db_path() -> Path:
    """The database this process should open.

    Read at import time by each caller, so JOBS_DB must be set before the
    process starts. That is the normal case for a CLI or a streamlit run.
    """
    return Path(os.environ.get("JOBS_DB") or DEFAULT_DB)
