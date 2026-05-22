from __future__ import annotations

import os
import subprocess
import re
import json
import urllib.request
from datetime import datetime
import time
import glob
from typing import Dict, List, Optional, Union, Tuple

from .config import settings


class ProcessingService:
    def __init__(self, amstrax_dir: str  = None, log_dir: str  = None, output_dir: str  = None):
        self.amstrax_dir = amstrax_dir or settings.stbc_amstrax_dir
        self.log_dir = log_dir or settings.stbc_log_dir
        self.output_dir = output_dir or settings.stbc_output_dir
        self._last_submit_by_run = {}  # type: Dict[int, float]
        self._cooldown_seconds = 45
        self._resource_profiles = {
            "8gb": {"mem": 8000, "queue": "short"},
            "16gb": {"mem": 16000, "queue": "short"},
            "32gb": {"mem": 32000, "queue": "short"},
        }
        self.default_amstrax_root = os.path.abspath(os.path.join(self.amstrax_dir, "..", ".."))

    def _run_cmd(self, cmd: list[str]) -> str:
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if p.returncode == 0:
                return (p.stdout or "").strip()
        except Exception:
            pass
        return ""

    def get_amstrax_info(self, amstrax_path: Optional[str] = None) -> dict:
        root = os.path.abspath((amstrax_path or self.default_amstrax_root).strip())
        info = {"path": root, "exists": os.path.isdir(root), "version": "", "branch": "", "commit": ""}
        if not info["exists"]:
            return info
        info["branch"] = self._run_cmd(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"])
        info["commit"] = self._run_cmd(["git", "-C", root, "rev-parse", "--short", "HEAD"])
        init_py = os.path.join(root, "amstrax", "__init__.py")
        if os.path.exists(init_py):
            try:
                txt = open(init_py, "r", encoding="utf-8").read()
                m = re.search(r"__version__\s*=\s*['\\\"]([^'\\\"]+)['\\\"]", txt)
                if m:
                    info["version"] = m.group(1)
            except Exception:
                pass
        return info

    def list_corrections_versions(self) -> list[str]:
        versions: list[str] = []
        # Source of truth: GitHub repository content listing.
        gh_url = (
            "https://api.github.com/repos/XAMS-nikhef/amstrax_files/contents/"
            "amstrax_files/corrections/_global"
        )
        try:
            with urllib.request.urlopen(gh_url, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    fn = str(item.get("name", ""))
                    m = re.match(r"^_global_(.+)\.json$", fn)
                    if m:
                        versions.append(m.group(1))
        except Exception:
            pass
        # Fallback path: ask amstrax by probing common versions.
        if not versions:
            probe = ["ONLINE", "v4", "v3", "v2", "v1", "v0", "dev"]
            try:
                import amstrax  # type: ignore
                for v in probe:
                    try:
                        _ = amstrax.get_correction(f"_global_{v}.json")
                        versions.append(v)
                    except Exception:
                        continue
            except Exception:
                pass
        if not versions:
            versions = ["ONLINE", "v2", "v1", "v0", "dev"]
        def _key(v: str):
            if v == "ONLINE":
                return (0, 0, v)
            mv = re.match(r"^v(\d+)$", v)
            if mv:
                return (1, -int(mv.group(1)), v)
            return (2, 0, v)
        return sorted(set(versions), key=_key)

    def summarize_corrections_for_run(self, run_id: int, corrections_version: str) -> dict:
        run_id_i = int(run_id)
        run_s = f"{run_id_i:06d}"
        out = {"run_id": run_id_i, "corrections_version": corrections_version, "ok": False, "entries": [], "error": ""}
        try:
            import amstrax  # type: ignore
            global_cfg = amstrax.get_correction(f"_global_{corrections_version}.json")
            if not isinstance(global_cfg, dict):
                out["error"] = "Global correction config is not a dict"
                return out
            entries = []
            for key, correction_file in global_cfg.items():
                ent = {"key": str(key), "file": str(correction_file), "matched_rule": "", "value_preview": "", "ok": False}
                try:
                    corr = amstrax.get_correction(str(correction_file))
                    if not isinstance(corr, dict):
                        ent["value_preview"] = f"type={type(corr).__name__}"
                        entries.append(ent)
                        continue
                    allow_wildcard = "_dev" in str(correction_file)
                    matched_rule = None
                    matched_val = None
                    for rule, val in corr.items():
                        if self._run_in_range(str(rule), run_id_i, allow_wildcard=allow_wildcard):
                            matched_rule = str(rule)
                            matched_val = val
                            break
                    if matched_rule is None:
                        ent["value_preview"] = "NO_MATCH"
                    else:
                        ent["matched_rule"] = matched_rule
                        ent["ok"] = True
                        if isinstance(matched_val, (int, float, str, bool)) or matched_val is None:
                            ent["value_preview"] = str(matched_val)
                        elif isinstance(matched_val, dict):
                            ent["value_preview"] = "{" + ", ".join(list(matched_val.keys())[:6]) + ("..." if len(matched_val) > 6 else "") + "}"
                        elif isinstance(matched_val, list):
                            ent["value_preview"] = f"list(len={len(matched_val)})"
                        else:
                            ent["value_preview"] = f"type={type(matched_val).__name__}"
                except Exception as e:
                    ent["value_preview"] = f"ERROR: {e}"
                entries.append(ent)
            out["entries"] = entries
            out["ok"] = all(e.get("ok") for e in entries) if entries else False
            return out
        except Exception as e:
            out["error"] = str(e)
            return out

    @staticmethod
    def _tail_text(path: str, max_bytes: int = 12000) -> str:
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - max_bytes), os.SEEK_SET)
                data = f.read().decode("utf-8", errors="replace")
            return data[-10000:]
        except Exception:
            return ""

    @staticmethod
    def _run_in_range(rule: str, run_id: int, allow_wildcard: bool = False) -> bool:
        run_s = f"{int(run_id):06d}"
        rule = str(rule).strip()
        if not rule:
            return False
        if "-" not in rule:
            return rule.zfill(6) == run_s
        start_run, end_run = rule.split("-", 1)
        start_run = start_run.strip()
        end_run = end_run.strip()
        if start_run == "*":
            if not allow_wildcard:
                return False
            start_run = "000000"
        if end_run == "*":
            if not allow_wildcard:
                return False
            end_run = "999999"
        start_run = start_run.zfill(6)
        end_run = end_run.zfill(6)
        return start_run <= run_s <= end_run

    def _validate_corrections_coverage(self, run_id: int, corrections_version: str) -> Tuple[bool, str]:
        try:
            import amstrax  # loaded in xams env on STBC
            global_cfg = amstrax.get_correction(f"_global_{corrections_version}.json")
        except Exception as e:
            return False, f"Invalid corrections version '{corrections_version}': {e}"

        if not isinstance(global_cfg, dict):
            return False, f"Invalid global corrections payload for '{corrections_version}'"

        for correction_key, correction_file in global_cfg.items():
            if not (isinstance(correction_file, str) and correction_file.endswith(".json")):
                continue
            try:
                correction_data = amstrax.get_correction(correction_file)
            except Exception as e:
                return False, f"Failed to load correction file '{correction_file}' for key '{correction_key}': {e}"
            if not isinstance(correction_data, dict):
                continue
            allow_wildcard = "_dev" in correction_file
            rules = [str(k) for k in correction_data.keys()]
            if not any(self._run_in_range(rule, run_id, allow_wildcard=allow_wildcard) for rule in rules):
                return (
                    False,
                    f"Corrections '{corrections_version}' not valid for run {int(run_id):06d}: "
                    f"no range match in {correction_file} (key={correction_key})",
                )
        return True, ""

    def list_corrections_compatibility(self, run_id: int) -> dict:
        versions = []
        try:
            import amstrax_files  # type: ignore
            root = os.path.join(os.path.dirname(amstrax_files.__file__), "..", "corrections", "_global")
            root = os.path.abspath(root)
            if os.path.isdir(root):
                for fn in os.listdir(root):
                    m = re.match(r"^_global_(.+)\.json$", fn)
                    if m:
                        versions.append(m.group(1))
        except Exception:
            pass
        if not versions:
            versions = ["ONLINE", "v2", "v1", "v0", "dev"]
        # Deterministic ordering: ONLINE, vN descending, then others.
        def _key(v: str):
            if v == "ONLINE":
                return (0, 0, v)
            mv = re.match(r"^v(\d+)$", v)
            if mv:
                return (1, -int(mv.group(1)), v)
            return (2, 0, v)
        versions = sorted(set(versions), key=_key)
        rows = []
        for ver in versions:
            ok, reason = self._validate_corrections_coverage(int(run_id), ver)
            rows.append({"version": ver, "compatible": bool(ok), "reason": "" if ok else reason})
        return {"run_id": int(run_id), "rows": rows}

    def _resolve_amstrax_path(self, amstrax_ref: Optional[str]) -> Optional[str]:
        if not amstrax_ref:
            return None
        ref = amstrax_ref.strip()
        if not ref:
            return None
        if os.path.isabs(ref):
            return ref
        # convention: refs map to subdirs in amstrax_versioned
        candidate = os.path.join("/data/xenon/xams_v2/software/amstrax_versioned", ref)
        return candidate

    def submit_run(
        self,
        run_id: int,
        target: Union[str, List[str]] = "events",
        corrections_version: Optional[str] = None,
        amstrax_ref: Optional[str] = None,
        resource_profile: str = "8gb",
    ) -> dict:
        now = time.time()
        last = self._last_submit_by_run.get(int(run_id), 0.0)
        targets = target if isinstance(target, list) else [target]
        rp = self._resource_profiles.get((resource_profile or "8gb").lower(), self._resource_profiles["8gb"])
        amstrax_path = self._resolve_amstrax_path(amstrax_ref)
        if now - last < self._cooldown_seconds:
            return {
                "run_id": int(run_id),
                "target": targets,
                "corrections_version": corrections_version,
                "amstrax_ref": amstrax_ref,
                "resource_profile": resource_profile,
                "job_name": None,
                "submitted": False,
                "returncode": 409,
                "stdout": "",
                "stderr": "Submission blocked: cooldown active for this run. Wait and refresh status.",
            }
        if corrections_version:
            ok, reason = self._validate_corrections_coverage(int(run_id), str(corrections_version))
            if not ok:
                return {
                    "run_id": int(run_id),
                    "target": targets,
                    "corrections_version": corrections_version,
                    "amstrax_ref": amstrax_ref,
                    "resource_profile": resource_profile,
                    "job_name": None,
                    "submitted": False,
                    "returncode": 422,
                    "stdout": "",
                    "stderr": reason,
                }

        run_id_s = f"{int(run_id):06d}"
        target_label = "_".join(targets)
        job_name = f"process_{run_id_s}_manual_{target_label}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        cmd = [
            "python",
            "auto_processing.py",
            "--run_id",
            run_id_s,
            "--target",
        ]
        cmd.extend(targets)
        cmd.extend(["--output_folder", self.output_dir, "--production"])
        cmd.extend(["--mem", str(int(rp["mem"]))])
        cmd.extend(["--queue", str(rp["queue"])])
        if corrections_version:
            cmd.extend(["--corrections_version", str(corrections_version)])
        if amstrax_path:
            cmd.extend(["--amstrax_path", str(amstrax_path)])
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            p = subprocess.run(cmd, cwd=self.amstrax_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if p.returncode == 0:
                self._last_submit_by_run[int(run_id)] = now
            return {
                "run_id": int(run_id),
                "target": targets,
                "corrections_version": corrections_version,
                "amstrax_ref": amstrax_ref,
                "amstrax_path": amstrax_path,
                "resource_profile": resource_profile,
                "job_name": job_name,
                "submitted": p.returncode == 0,
                "returncode": p.returncode,
                "stdout": p.stdout[-4000:],
                "stderr": p.stderr[-4000:],
            }
        except Exception as e:
            return {
                "run_id": int(run_id),
                "target": targets,
                "corrections_version": corrections_version,
                "amstrax_ref": amstrax_ref,
                "amstrax_path": amstrax_path,
                "resource_profile": resource_profile,
                "job_name": job_name,
                "submitted": False,
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
            }

    def get_run_job_logs(self, run_id: int, limit: int = 6) -> dict:
        run_token = f"{int(run_id):06d}"
        log_dir = self.log_dir
        patterns = [
            os.path.join(log_dir, f"*{run_token}*.out"),
            os.path.join(log_dir, f"*{run_token}*.log"),
            os.path.join(log_dir, f"*{run_token}*.sh"),
        ]
        files = []
        seen = set()
        for p in patterns:
            for fp in glob.glob(p):
                if fp in seen:
                    continue
                seen.add(fp)
                try:
                    st = os.stat(fp)
                except Exception:
                    continue
                files.append(
                    {
                        "path": fp,
                        "name": os.path.basename(fp),
                        "mtime": datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                        "size_bytes": int(st.st_size),
                        "tail": self._tail_text(fp),
                    }
                )
        files = sorted(files, key=lambda x: x["mtime"], reverse=True)[: max(1, int(limit))]
        return {"run_id": int(run_id), "count": len(files), "files": files}
