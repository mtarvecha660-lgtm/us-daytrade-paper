import os
HERE = os.path.dirname(os.path.abspath(__file__))

def load_universe(path=os.path.join(HERE, "universe.txt")):
    out = []
    with open(path) as fh:
        lines = fh.read().splitlines()
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.upper())
    return out
