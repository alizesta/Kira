"""Windows Bluetooth control: read the state, switch the radio on, switch it off - three independent tools.

Method: the official Windows Runtime radio API (Windows.Devices.Radios.Radio: RequestAccessAsync / GetRadiosAsync / SetStateAsync - the same API
the Settings app uses), reached through Windows PowerShell 5.1 (shared runner: winrunner.py) with a FIXED script. No user or model text is ever part of the script: the only
variable is a literal chosen from a closed list (read / On / Off). Nothing is run through a shell string and no arbitrary command exists.

Every change is verified: after SetStateAsync the radio is read again (up to ~6 s) and only the real state is reported.
"""
from __future__ import annotations

import sys
import threading
import time

from .registry import ToolError, DENIED, ERROR
from .winrunner import FixedScript, run_fixed          # shared controlled PowerShell runner (also used by Audio)

IS_WIN = sys.platform == "win32"
_LOCK = threading.Lock()

_SCRIPT = r"""
$ErrorActionPreference='Stop'
$out=[ordered]@{ok=$true;access='';service='';radios=@();set='';error=''}
try{
  try{$out.service=[string](Get-Service -Name bthserv -ErrorAction Stop).Status}catch{$out.service='missing'}
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null=[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]
  $null=[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime]
  $m=[System.WindowsRuntimeSystemExtensions].GetMethods()|Where-Object{$_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'}|Select-Object -First 1
  function Wait-Op($op,$type){$t=$m.MakeGenericMethod($type).Invoke($null,@($op));if(-not $t.Wait(15000)){throw 'timeout waiting for Windows radio API'};$t.Result}
  $out.access=[string](Wait-Op ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]))
  $list=Wait-Op ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
  foreach($r in $list){
    if([string]$r.Kind -eq 'Bluetooth'){
      @@SET@@
      $out.radios+=,@{name=[string]$r.Name;state=[string]$r.State}
    }
  }
}catch{$out.ok=$false;$out.error=[string]$_.Exception.Message}
$out|ConvertTo-Json -Compress -Depth 4
"""
_SET_TEMPLATE = ("if([string]$r.State -ne '@@V@@'){$out.set+=([string](Wait-Op ($r.SetStateAsync([Windows.Devices.Radios.RadioState]::@@V@@)) "
                 "([Windows.Devices.Radios.RadioAccessStatus])))+';'}")
_SCRIPTS = {"read": FixedScript("bluetooth-read", _SCRIPT.replace("@@SET@@", "")),
            "On": FixedScript("bluetooth-on", _SCRIPT.replace("@@SET@@", _SET_TEMPLATE.replace("@@V@@", "On"))),
            "Off": FixedScript("bluetooth-off", _SCRIPT.replace("@@SET@@", _SET_TEMPLATE.replace("@@V@@", "Off")))}


def _run(mode: str) -> dict:
    """Run one of the three fixed scripts. -> parsed JSON, or {'ok': False, 'error': ...} when Windows PowerShell itself failed."""
    data = run_fixed(_SCRIPTS[mode], timeout=45, api_name="بلوتوث ویندوز")   # KeyError = programming error: only the three fixed modes exist
    if data.get("fatal"):
        return data
    radios = data.get("radios") or []
    data["radios"] = [radios] if isinstance(radios, dict) else list(radios)
    return data


def _interpret(data: dict) -> dict:
    """-> {'state': on|off|disabled|mixed|no_adapter|denied|unknown, 'detail': str, 'names': [...]}"""
    service = str(data.get("service") or "")
    access = str(data.get("access") or "")
    svc_note = ""
    if service == "missing":
        svc_note = " سرویس «Bluetooth Support Service» (bthserv) روی این سیستم ثبت نشده است."
    elif service and service != "Running":
        svc_note = f" سرویس «Bluetooth Support Service» در حالت {service} است (برای اتصال دستگاه‌ها لازم است؛ در Services.msc روی Manual/Automatic و Start باشد)."
    if not data.get("ok"):
        err = str(data.get("error") or "نامشخص")
        low = err.lower()
        if "access" in low and "denied" in low or "unauthorized" in low or "دسترسی" in err:
            return {"state": "denied", "detail": f"ویندوز اجازه‌ی دسترسی به رادیوها را نداد: {err}.{svc_note}", "names": []}
        return {"state": "unknown", "detail": f"وضعیت خوانده نشد: {err}.{svc_note}", "names": []}
    if access in ("DeniedByUser", "DeniedBySystem"):
        why = ("در Settings ← Privacy & security ← Radios گزینه‌ی «Let apps control radios» خاموش است یا برای این برنامه رد شده"
               if access == "DeniedByUser" else "سیاست سیستم (Group Policy / مدیر سیستم) دسترسی به رادیوها را بسته است")
        return {"state": "denied", "detail": f"دسترسی به کنترل رادیو رد شد ({access}): {why}.", "names": []}
    radios = data.get("radios") or []
    if not radios:
        return {"state": "no_adapter", "detail": "هیچ آداپتور بلوتوثی توسط ویندوز شناسایی نشد (آداپتور وجود ندارد، درایور نصب نیست، در Device Manager غیرفعال است، "
                                                "یا سخت‌افزار جدا شده)." + svc_note, "names": []}
    states = [str(r.get("state")) for r in radios]
    names = [f"{r.get('name') or 'Bluetooth'}: {r.get('state')}" for r in radios]
    if all(s == "On" for s in states):
        state = "on"
    elif all(s == "Off" for s in states):
        state = "off"
    elif any(s == "Disabled" for s in states):
        state = "disabled"
    elif any(s == "On" for s in states) and any(s == "Off" for s in states):
        state = "mixed"
    else:
        state = "unknown"
    return {"state": state, "detail": svc_note.strip(), "names": names}


_FA = {"on": "روشن", "off": "خاموش", "disabled": "غیرفعال از سمت سیستم/سخت‌افزار", "mixed": "ترکیبی (چند آداپتور با وضعیت متفاوت)",
       "no_adapter": "آداپتور شناسایی نشد", "denied": "خطای دسترسی", "unknown": "نامشخص"}


def _report(info: dict) -> str:
    parts = [f"وضعیت بلوتوث: {_FA[info['state']]}."]
    if info["names"]:
        parts.append("آداپتور: " + " ، ".join(info["names"]) + ".")
    if info["state"] == "disabled":
        parts.append("ویندوز می‌گوید رادیو Disabled است: معمولاً حالت هواپیما (Airplane mode)، کلید/دکمه‌ی سخت‌افزاری وایرلس، یا غیرفعال بودن در Device Manager. از طریق API نمی‌شود آن را روشن کرد.")
    if info["detail"]:
        parts.append(info["detail"])
    return " ".join(parts)


def _read() -> dict:
    return _interpret(_run("read"))


class BluetoothTools:
    @staticmethod
    def _need_windows():
        if not IS_WIN:
            raise ToolError("کنترل بلوتوث فقط روی ویندوز ممکن است.")

    def status(self, a: dict) -> str:
        if not IS_WIN:
            return "وضعیت بلوتوث: نامشخص؛ خواندن بلوتوث فقط روی ویندوز ممکن است."
        with _LOCK:
            return _report(_read())

    def turn_on(self, a: dict) -> str:
        return self._switch(True)

    def turn_off(self, a: dict) -> str:
        return self._switch(False)

    def _switch(self, want_on: bool) -> str:
        self._need_windows()
        want, word, mode = ("on" if want_on else "off"), ("روشن" if want_on else "خاموش"), ("On" if want_on else "Off")
        with _LOCK:
            before = _read()
            if before["state"] == want:
                return f"بلوتوث از قبل {word} بود؛ تغییری لازم نبود. (بررسی واقعی: {_report(before)})"
            if before["state"] in ("no_adapter", "denied", "unknown", "disabled"):
                raise ToolError(f"بلوتوث {word} نشد و تغییری اعمال نشد. {_report(before)}",
                                DENIED if before["state"] == "denied" else ERROR)
            data = _run(mode)
            result = str(data.get("set") or "").strip("; ")
            after = _interpret(data) if data.get("ok") is False else before
            for _ in range(6):                                  # the radio needs a moment: check the REAL state again
                time.sleep(1.0)
                after = _read()
                if after["state"] == want:
                    return f"بلوتوث {word} شد و بعد از عملیات دوباره بررسی شد: {_report(after)}"
            reasons = []
            if data.get("ok") is False:
                reasons.append(f"خطای API: {data.get('error')}")
            if "Denied" in result:
                reasons.append(f"ویندوز اجازه‌ی تغییر را نداد ({result}): Settings ← Privacy & security ← Radios را بررسی کن یا سیاست سیستم مانع است")
            elif result and "Allowed" not in result:
                reasons.append(f"نتیجه‌ی ویندوز: {result}")
            if after["state"] == "disabled":
                reasons.append("رادیو Disabled شد/است (حالت هواپیما یا کلید سخت‌افزاری)")
            raise ToolError(f"بلوتوث {word} نشد؛ وضعیت واقعی بعد از عملیات: {_report(after)} " + (" علت: " + " | ".join(reasons) + "." if reasons else
                            " علت مشخصی از ویندوز گزارش نشد (ممکن است درایور/سخت‌افزار فرمان را نادیده گرفته باشد)."))
