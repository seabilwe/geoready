"""Run record (Implementation Guide p.3): every run has a run_id, model
version, study area, baseline year, scenario, parameter file, software
lockfile, input checksums, timestamps, QA report and output manifest."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

import yaml

from . import __version__


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def lockfile():
    try:
        out = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True,
                             text=True, timeout=120).stdout
        return sorted(l for l in out.splitlines() if l and not l.startswith("-e"))
    except Exception as e:  # pragma: no cover
        return [f"unavailable: {e}"]


class Run:
    """Holds the record for one run and writes it to runs/<run_id>/run.json."""

    def __init__(self, config_path, root="."):
        self.root = Path(root)
        self.config_path = Path(config_path)
        self.cfg = load_config(self.config_path)
        self.inputs = {}
        files = dict(self.cfg.get("grids", {}))
        if "vectors" in self.cfg:
            files["vectors"] = self.cfg["vectors"]
        for key, rel in files.items():
            p = self.root / rel
            self.inputs[key] = {"path": rel, "sha256": sha256(p) if p.exists() else None}
        h = hashlib.sha256(self.config_path.read_bytes())
        for k in sorted(self.inputs):
            h.update(str(self.inputs[k]["sha256"]).encode())
        today = _dt.date.today().isoformat()
        self.run_id = f"{today}_{self.cfg['scenario_id']}_{h.hexdigest()[:8]}"
        self.dir = self.root / "runs" / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.record = {
            "run_id": self.run_id,
            "model_id": "geoready",
            "model_version": __version__,
            "study_area": self.cfg["study_area"],
            "baseline_year": self.cfg["baseline_year"],
            "scenario_id": self.cfg["scenario_id"],
            "parameter_file": str(self.config_path),
            "parameter_sha256": sha256(self.config_path),
            "inputs": self.inputs,
            "software": {"python": sys.version.split()[0], "platform": platform.platform(),
                         "packages": lockfile()},
            "started": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "finished": None,
            "qa": None,
            "outputs": {},
        }
        missing = [k for k, v in self.inputs.items() if v["sha256"] is None]
        if missing:
            print("Missing inputs (download them first, see data/README.md):", ", ".join(missing))

    def path(self, name):
        return self.dir / name

    def add_output(self, name, description=""):
        p = self.path(name)
        self.record["outputs"][name] = {"sha256": sha256(p), "bytes": p.stat().st_size,
                                        "description": description}

    def finish(self, qa: dict):
        self.record["qa"] = qa
        self.record["finished"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        with open(self.path("run.json"), "w", encoding="utf-8") as f:
            json.dump(self.record, f, indent=1)
        return self.record
