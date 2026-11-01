"""Load the day-trader-skill's own tools (vendored unchanged in skill/) as Python modules."""
import importlib.util
import os
import sys

SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skill")


def _load(name, filename):
    key = "dtskill_" + name
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, os.path.join(SKILL_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


scan = _load("scan", "scan.py")          # trader-scanner
entry = _load("entry", "entry.py")       # trader-entry
exitp = _load("exit", "exit.py")         # trader-exit
size = _load("size", "size.py")          # trader-budget
risk = _load("check", "check.py")        # trader-risk
timemachine = _load("timemachine", "timemachine.py")  # trader-timemachine
