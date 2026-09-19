import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEMO = os.path.join(ROOT, "examples", "demo-session.jsonl")


@pytest.fixture(scope="session")
def demo_path():
    if not os.path.exists(DEMO):
        subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "make_demo.py"), DEMO])
    return DEMO


@pytest.fixture(scope="session")
def profile(demo_path):
    from agentprof.analyze import analyze
    from agentprof.ingest import read_auto
    return analyze(read_auto(demo_path)[1], source="demo")
