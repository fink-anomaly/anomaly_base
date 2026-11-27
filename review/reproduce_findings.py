"""Run the maintained regressions for the original review findings.

The original one-off probes were superseded by these isolated tests. Fixed
security issues must pass; four remaining P2 cases are strict expected failures.
No external API calls or production database access are performed.
"""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.run([
    sys.executable, '-m', 'pytest', 'tests/test_security.py',
    'tests/test_known_regressions.py', '-q',
], cwd=root).returncode)
