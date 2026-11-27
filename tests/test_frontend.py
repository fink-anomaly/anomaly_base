"""Include the dependency-free JavaScript behavior tests in the full run."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js 18+ is required for frontend tests')
def test_tns_frontend():
    result = subprocess.run(
        ['node', '--test', str(Path(__file__).parent / 'js' / 'tns.test.cjs')],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
