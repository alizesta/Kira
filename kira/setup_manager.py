"""Explicit lifecycle manager for the optional local Ollama runtime."""
from __future__ import annotations
import argparse
import ctypes
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Callable
from urllib.parse import quote
import requests
from .ollama_client import resolve_model

DEFAULT_OLLAMA_URL = "http://localhost:11434"
REGISTRY_URL = "https://registry.ollama.ai"
MANIFEST_ACCEPT = "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json"
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$")

class SetupError(RuntimeError):
    """A user-actionable setup failure."""

@dataclass(frozen=True)
class SetupSnapshot:
    executable: str | None
    server_reachable: bool
    version: str | None
    installed_models: tuple[str, ...]
    selected_model: str
    resolved_model: str | None
    selected_model_installed: bool
    selected_model_runnable: bool
    error: str | None = None
    @property
    def ready(self):
        return self.server_reachable and self.selected_model_installed and self.selected_model_runnable

@dataclass(frozen=True)
class ModelManifest:
    model: str
    total_bytes: int
    layers: int

@dataclass(frozen=True)
class HardwareProfile:
    ram_bytes: int | None
    vram_bytes: int | None
    def assess(self, model_bytes):
        if self.vram_bytes is not None and self.vram_bytes >= model_bytes * 1.10:
            return "gpu_fit", "مدل با حاشیهٔ ۱۰٪ در VRAM شناسایی‌شده جا می‌شود."
        if self.ram_bytes is not None and self.ram_bytes >= model_bytes * 1.50:
            return "ram_fit", "مدل احتمالاً با Offload روی RAM/CPU اجرا می‌شود؛ سرعت تضمین‌شده نیست."
        if self.ram_bytes is None and self.vram_bytes is None:
            return "unknown", "مشخصات حافظه قابل تشخیص نیست؛ سازگاری نامشخص است."
        return "constrained", "حافظهٔ شناسایی‌شده برای اجرای مطمئن مدل کافی به نظر نمی‌رسد."

def _physical_ram_bytes():
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),
                ("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),
                ("ullTotalPageFile",ctypes.c_ulonglong),("ullAvailPageFile",ctypes.c_ulonglong),
                ("ullTotalVirtual",ctypes.c_ulonglong),("ullAvailVirtual",ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual",ctypes.c_ulonglong)]
        status=MEMORYSTATUSEX(); status.dwLength=ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except (ImportError,OSError):
        return None

def _nvidia_vram_bytes(runner=subprocess.run):
    executable=shutil.which("nvidia-smi")
    if not executable: return None
    try:
        result=runner([executable,"--query-gpu=memory.total","--format=csv,noheader,nounits"],
            capture_output=True,text=True,timeout=5,check=False)
        if result.returncode: return None
        values=[int(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        return max(values)*1024*1024 if values else None
    except (OSError,ValueError,subprocess.SubprocessError):
        return None

def hardware_profile():
    return HardwareProfile(_physical_ram_bytes(),_nvidia_vram_bytes())

def _model_parts(model):
    value=str(model or "").strip()
    if not MODEL_RE.fullmatch(value) or ".." in value or value.startswith("/") or value.endswith("/"):
        raise ValueError("شناسهٔ مدل معتبر نیست؛ نمونه: qwen3.5:4b یا namespace/model:tag")
    name,sep,tag=value.rpartition(":")
    if not sep: name,tag=value,"latest"
    if "/" not in name: name="library/"+name
    return name,tag

def registry_manifest(model, *, session=requests, timeout=20):
    name,tag=_model_parts(model)
    url=f"{REGISTRY_URL}/v2/{quote(name,safe='/')}/manifests/{quote(tag,safe='')}"
    response=session.get(url,headers={"Accept":MANIFEST_ACCEPT},timeout=timeout)
    if response.status_code==404: raise SetupError(f"مدل «{model}» در Ollama Registry پیدا نشد.")
    response.raise_for_status()
    layers=response.json().get("layers")
    if not isinstance(layers,list) or not layers: raise SetupError("Registry اندازهٔ لایه‌های مدل را برنگرداند؛ دانلود شروع نشد.")
    sizes=[]
    for layer in layers:
        size=layer.get("size") if isinstance(layer,dict) else None
        if not isinstance(size,int) or size<0: raise SetupError("Manifest مدل اندازهٔ معتبر ندارد.")
        sizes.append(size)
    return ModelManifest(model,sum(sizes),len(sizes))

def model_store_path():
    return Path(os.environ["OLLAMA_MODELS"]).expanduser() if os.environ.get("OLLAMA_MODELS") else Path.home()/".ollama"/"models"

def _existing_parent(path):
    current=path
    while not current.exists() and current!=current.parent: current=current.parent
    return current

class OllamaSetupManager:
    def __init__(self,base_url=DEFAULT_OLLAMA_URL,*,session=requests,executable_finder=shutil.which,
        runner=subprocess.run,popen=subprocess.Popen,disk_usage=shutil.disk_usage,store_path=None,selected_model=""):
        self.base_url=str(base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        self.session,self.executable_finder,self.runner,self.popen=session,executable_finder,runner,popen
        self.disk_usage=disk_usage
        self.store_path=Path(store_path) if store_path else model_store_path()
        self.selected_model=str(selected_model or "").strip()

    def executable(self):
        found=self.executable_finder("ollama")
        if found: return str(found)
        if os.name=="nt":
            roots=(Path(os.environ.get("LOCALAPPDATA",""))/"Programs"/"Ollama"/"ollama.exe",
                Path(os.environ.get("ProgramFiles","C:/Program Files"))/"Ollama"/"ollama.exe")
            return next((str(p) for p in roots if p.is_file()),None)
        return None

    def _get_json(self,endpoint,timeout=5):
        response=self.session.get(f"{self.base_url}{endpoint}",timeout=timeout)
        response.raise_for_status()
        payload=response.json()
        if not isinstance(payload,dict): raise SetupError(f"پاسخ Ollama برای {endpoint} معتبر نیست.")
        return payload

    def installed_models(self):
        models=self._get_json("/api/tags").get("models")
        if not isinstance(models,list): raise SetupError("فهرست مدل‌های نصب‌شده معتبر نیست.")
        return tuple(str(m.get("name") or m.get("model") or "") for m in models
            if isinstance(m,dict) and (m.get("name") or m.get("model")))

    def probe_model(self,model,timeout=90):
        if not model: return False
        response=self.session.post(f"{self.base_url}/api/generate",json={
            "model":model,"prompt":"Reply with OK.","stream":False,"keep_alive":0,
            "options":{"num_predict":8,"temperature":0}},timeout=timeout)
        if response.status_code>=400: return False
        payload=response.json()
        return isinstance(payload,dict) and bool(str(payload.get("response") or "").strip())

    def inspect(self):
        executable=self.executable()
        try:
            version=str(self._get_json("/api/version").get("version") or "")
            installed=self.installed_models()
        except (requests.RequestException,ValueError,SetupError) as exc:
            return SetupSnapshot(executable,False,None,(),self.selected_model,None,False,False,str(exc))
        resolved=resolve_model(installed,self.selected_model)
        present=resolved is not None
        runnable=False; error=None
        if present:
            try:
                runnable=self.probe_model(resolved)
                if not runnable: error=f"مدل انتخاب‌شده «{self.selected_model}» (نسخهٔ نصب‌شده: «{resolved}») نصب است اما اجرای مستقل آن موفق نبود."
            except (requests.RequestException,ValueError) as exc: error=str(exc)
        return SetupSnapshot(executable,True,version,installed,self.selected_model,resolved,present,runnable,error)

    def install_engine(self):
        if os.name!="nt": raise SetupError("نصب خودکار Ollama فقط در Windows پشتیبانی می‌شود.")
        winget=self.executable_finder("winget")
        if not winget: raise SetupError("winget پیدا نشد؛ Ollama را با نصب‌کنندهٔ رسمی نصب کن.")
        result=self.runner([winget,"install","--id","Ollama.Ollama","--exact","--silent",
            "--accept-package-agreements","--accept-source-agreements"],check=False,timeout=900)
        if result.returncode: raise SetupError(f"نصب Ollama با کد {result.returncode} متوقف شد.")
        executable=self.executable()
        if not executable: raise SetupError("نصب اجرا شد اما ollama.exe پیدا نشد؛ PATH را تازه‌سازی کن.")
        return executable

    def start_server(self):
        executable=self.executable()
        if not executable: raise SetupError("فایل اجرایی Ollama پیدا نشد.")
        flags=(getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"DETACHED_PROCESS",0)) if os.name=="nt" else 0
        self.popen([executable,"serve"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=flags)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try: self._get_json("/api/version",timeout=2); return
            except (requests.RequestException,ValueError,SetupError): time.sleep(1)
        raise SetupError("سرور Ollama ظرف ۳۰ ثانیه آماده نشد.")

    def preflight(self,model,*,profile=None):
        manifest=registry_manifest(model,session=self.session)
        required=int(manifest.total_bytes*1.10)
        free=int(self.disk_usage(_existing_parent(self.store_path)).free)
        assessment,explanation=(profile or hardware_profile()).assess(manifest.total_bytes)
        if free<required:
            raise SetupError(f"فضای آزاد کافی نیست: {_gb(required)} لازم است و {_gb(free)} آزاد است؛ دانلود شروع نشد.")
        return manifest,required,assessment,explanation

    def pull_model(self,model,*,progress=None):
        if not MODEL_RE.fullmatch(str(model or "").strip()): raise ValueError("شناسهٔ مدل معتبر نیست.")
        if resolve_model(self.installed_models(),model) is not None: return
        self.preflight(model)
        response=self.session.post(f"{self.base_url}/api/pull",json={"model":model,"stream":True},
            stream=True,timeout=(10,60))
        response.raise_for_status()
        for raw in response.iter_lines(decode_unicode=True):
            if not raw: continue
            item=json.loads(raw)
            if item.get("error"): raise SetupError(f"دانلود مدل ناموفق بود: {item['error']}")
            if progress: progress(item)
        if model not in self.installed_models():
            raise SetupError("Pull پایان یافت اما مدل ثبت نشده است؛ تنظیمات انتخاب‌شده تغییر نکرد.")

    def select_model(self,model):
        from . import config,routes
        settings=config.load_settings()
        candidates=[r for r in routes.get_routes(settings) if r.get("provider")=="ollama"]
        if not candidates: raise SetupError("Route محلی Ollama در تنظیمات پیدا نشد.")
        current=configured_local_model(settings)
        target=next((r for r in candidates if r.get("model")==current),candidates[0])
        routes.update_route(settings,target["id"],model=model)
        settings["model"]=model
        settings.setdefault("providers",{}).setdefault("ollama",{})["model"]=model
        for role in ("surface","memory"):
            allowed=settings.setdefault("role_route_models",{}).setdefault(role,[])
            if model not in allowed: allowed.append(model)
        config.save_settings(settings)
        self.selected_model=model

def _gb(value): return f"{value/1_000_000_000:.2f} GB"

def configured_local_model(settings):
    """Resolve the effective surface-role Ollama model from canonical Routes, not legacy mirrors."""
    from . import routes
    candidates=[r for r in routes.get_routes(settings)
        if r.get("provider")=="ollama" and r.get("enabled",True)]
    allowed=settings.get("role_route_models",{}).get("surface")
    if isinstance(allowed,(list,tuple)) and allowed:
        candidates=[r for r in candidates if r.get("model") in allowed]
    manual=str(settings.get("manual_route_id") or "")
    selected=next((r for r in candidates if r.get("id")==manual),None)
    if selected is None and candidates:
        selected=candidates[0]
    if selected and selected.get("model"):
        return str(selected["model"])
    return str((settings.get("providers",{}).get("ollama") or {}).get("model")
        or settings.get("model") or "")

def _load_selected_model():
    from .config import load_settings
    return configured_local_model(load_settings())

def _interactive():
    selected=_load_selected_model()
    manager=OllamaSetupManager(selected_model=selected)
    snapshot=manager.inspect()
    print("\n=== Kira Local Runtime Setup ===")
    if snapshot.server_reachable:
        print(f"Ollama reachable: version {snapshot.version}")
        print("Installed models: "+(", ".join(snapshot.installed_models) or "none"))
    else:
        print(f"Ollama not reachable: {snapshot.error or 'server offline'}")
        if not manager.executable():
            if input("Install Ollama with Windows Package Manager? [y/N]: ").strip().lower()!="y":
                print("Ollama installation skipped; Kira core remains installed."); return 0
            try: manager.install_engine()
            except (SetupError,OSError,subprocess.SubprocessError) as exc:
                print(f"OLLAMA ENGINE SETUP FAILED: {exc}"); return 1
        if input("Start the local Ollama server now? [Y/n]: ").strip().lower() not in ("","y","yes"):
            print("Ollama is installed but runtime is not ready; rerun setup later."); return 0
        try: manager.start_server()
        except (SetupError,OSError,subprocess.SubprocessError) as exc:
            print(f"OLLAMA SERVER SETUP FAILED: {exc}"); return 1
    model=input(f"Model ID to prepare [{selected}]: ").strip() or selected
    try:
        installed=manager.installed_models()
        if resolve_model(installed,model) is not None:
            manifest,required,fit,detail=ModelManifest(model,0,0),0,"already_installed","این مدل یا نام مستعار سازگار آن از قبل نصب است."
        else:
            manifest,required,fit,detail=manager.preflight(model)
    except (SetupError,ValueError,requests.RequestException) as exc:
        print(f"MODEL PREFLIGHT FAILED: {exc}"); return 1
    print(f"Model: {model}")
    print(f"Registry size: {_gb(manifest.total_bytes)}; required free space: {_gb(required)}")
    print(f"Hardware: {fit} — {detail}")
    if fit=="constrained": print("Warning: this model may fail to load or run very slowly.")
    if input("Download/verify this model now? [y/N]: ").strip().lower()!="y":
        print("Download skipped; selected model setting was not changed."); return 0
    def progress(item):
        total=int(item.get("total") or 0); done=int(item.get("completed") or 0)
        if total: print(f"\r{item.get('status','downloading')}: {done*100//total:3d}%",end="",flush=True)
        elif item.get("status"): print(item["status"])
    try: manager.pull_model(model,progress=progress)
    except KeyboardInterrupt:
        print("\nDownload interrupted. Ollama keeps partial layers; rerun setup to resume."); return 1
    except (SetupError,requests.RequestException,ValueError) as exc:
        print(f"\nMODEL DOWNLOAD FAILED: {exc}")
        print("No route setting was changed. Rerun setup to resume."); return 1
    print(f"\nModel «{model}» is installed.")
    if input("Select it as Kira's local chat model? [y/N]: ").strip().lower()=="y":
        try: manager.select_model(model)
        except (SetupError,OSError,ValueError) as exc:
            print(f"Model is installed but could not be selected: {exc}"); return 1
    else: print("Installed but not selected; existing route settings are preserved.")
    final=OllamaSetupManager(selected_model=_load_selected_model()).inspect()
    print(f"Runtime ready: {'yes' if final.ready else 'no'}")
    if final.error: print(final.error)
    return 0 if final.ready else 1

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--interactive",action="store_true")
    group.add_argument("--status",action="store_true")
    args=parser.parse_args(argv)
    if args.interactive: return _interactive()
    snapshot=OllamaSetupManager(selected_model=_load_selected_model()).inspect()
    print(json.dumps(asdict(snapshot)|{"ready":snapshot.ready},ensure_ascii=False,indent=2))
    return 0 if snapshot.ready else 1

if __name__=="__main__": raise SystemExit(main())
