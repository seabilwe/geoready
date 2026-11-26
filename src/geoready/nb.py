"""Notebook helpers that behave the same in Jupyter and in QGIS.

The QGIS Notebook plugin runs cells with QGIS's own Python and shows printed
text, not rich output. show() renders tables and figures in Jupyter and
prints or saves them in QGIS, so one notebook works in both.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _ipython():
    try:
        from IPython import get_ipython
        return get_ipython() is not None
    except Exception:
        return False


def find_root(start=None):
    """Repo root: GEOREADY_ROOT, else walk up from the working directory,
    else from the folder the QGIS Notebook plugin last opened a file in."""
    if os.environ.get("GEOREADY_ROOT"):
        return Path(os.environ["GEOREADY_ROOT"])
    starts = [Path(start or Path.cwd())]
    try:
        from qgis.PyQt.QtCore import QSettings
        last = QSettings().value("QGISNotebook/last_directory", "")
        if last:
            starts.append(Path(last))
    except Exception:
        pass
    for s in starts:
        for p in [s, *s.parents]:
            if (p / "pyproject.toml").exists() and (p / "src" / "geoready").exists():
                return p
    return None


def show(obj, save_as=None):
    """Display a DataFrame, Series or matplotlib Figure in either host."""
    import matplotlib.figure
    if _ipython():
        from IPython.display import display
        display(obj)
        if isinstance(obj, matplotlib.figure.Figure):
            import matplotlib.pyplot as plt
            plt.close(obj)
        return None
    if isinstance(obj, matplotlib.figure.Figure):
        path = Path(save_as or Path.cwd() / "figure.png")
        obj.savefig(path, dpi=130, bbox_inches="tight")
        print(f"[figure saved: {path}]")
        return None
    to_string = getattr(obj, "to_string", None)
    print(to_string() if to_string else obj)
    return None


def run_tests(path="tests"):
    """Run the unit tests in a separate Python process.

    Never in-process: pytest inside the QGIS GUI process is not safe. In
    QGIS, use the Python that ships with it rather than sys.executable.
    """
    import subprocess
    exe, env = sys.executable, dict(os.environ)
    if "qgis" in sys.modules:
        cand = Path(sys.prefix) / ("python.exe" if os.name == "nt" else "bin/python3")
        if cand.exists():
            exe = str(cand)
            env["PYTHONHOME"] = sys.prefix
    flags = 0x08000000 if os.name == "nt" else 0   # no console window on Windows
    try:
        r = subprocess.run([exe, "-m", "pytest", "-q", "--color=no", "-p", "no:cacheprovider", str(path)],
                           capture_output=True, text=True, env=env, creationflags=flags, timeout=900)
    except Exception as e:  # pragma: no cover
        return {"check": "unit tests", "passed": False, "detail": f"could not run: {e}"}
    lines = r.stdout.strip().splitlines() or r.stderr.strip().splitlines() or ["no output"]
    return {"check": "unit tests", "passed": r.returncode == 0, "detail": lines[-1]}
