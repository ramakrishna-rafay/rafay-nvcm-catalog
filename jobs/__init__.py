# Job discovery for the git sync: importing the module chain is what executes register_jobs() — the
# working legacy repo does exactly this (`from . import load_bootstrap_data`). A bare marker file would
# make the package importable and STILL register nothing.
from .load_bootstrap_data import jobs  # noqa: F401
