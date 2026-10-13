"""`python -m services.edge.report ...`: the report CLI (D-023); the code is in reports/."""

import sys

from services.edge.reports.cli import main

if __name__ == "__main__":
    sys.exit(main())
