"""Windows Audio Manager: system volume / mute, per-application volume, device lists and default input / output devices.

Method: the Windows Core Audio COM APIs (MMDevice API + WASAPI endpoint / session volume: IMMDeviceEnumerator, IAudioEndpointVolume,
IAudioSessionManager2, ISimpleAudioVolume - the same APIs the Windows volume slider and Volume Mixer use), reached from Windows PowerShell 5.1
through the shared runner (winrunner.py) with ONE FIXED script (a small C# interop class compiled by Add-Type). No new Python dependency.
The only Windows API with no public equivalent is "set default device": it uses the undocumented IPolicyConfig interface that every
audio switcher (SoundSwitch, EarTrumpet, AudioDeviceCmdlets ...) uses. If a future Windows build changes it, the tool reports a clear error.

Safety:
  * The script never contains user / model text. Variable data travels as ONE JSON environment variable (KIRA_AUDIO_REQ) that the script parses as data.
  * Python validates every value first: integers are range-checked, `op` / `mode` come from closed lists, a device id is always one the system
    itself reported (never the model's words), session ids are always taken from a live listing.
  * Every change is verified: the script changes the state, waits a moment and then reads it again through FRESH COM objects; Python compares the
    real result with the request and reports the real state - or an error. "Success" is never assumed.
"""
from __future__ import annotations

import json
import re
import sys
import threading

from .registry import ToolError, DENIED, ERROR, BAD_ARGS
from .winrunner import FixedScript, run_fixed

IS_WIN = sys.platform == "win32"
_LOCK = threading.Lock()
_OPS = {"state", "devices", "sessions", "volume", "mute", "session_set", "set_default"}
_ID_RX = re.compile(r"^\{[0-9]\.[0-9]\.[0-9]\.[0-9]{8}\}\.\{[0-9A-Fa-f\-]{36}\}$")      # an MMDevice endpoint id
TOLERANCE = 1                                                                            # drivers may round the level by one percent

# ------------------------------------------------------------------------------------------------ the FIXED script
_CSHARP = r"""
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

namespace KiraAudio
{
    [StructLayout(LayoutKind.Sequential)]
    struct PropertyKey { public Guid fmtid; public int pid; }

    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    class MMDeviceEnumeratorCom { }

    [ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
    class PolicyConfigClient { }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDeviceEnumerator
    {
        void EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
        void GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
        void GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
        void RegisterEndpointNotificationCallback(IntPtr client);
        void UnregisterEndpointNotificationCallback(IntPtr client);
    }

    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDeviceCollection
    {
        void GetCount(out int count);
        void Item(int index, out IMMDevice device);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMMDevice
    {
        void Activate(ref Guid iid, int clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object iface);
        void OpenPropertyStore(int access, out IPropertyStore store);
        void GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
        void GetState(out int state);
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore
    {
        void GetCount(out int count);
        void GetAt(int index, out PropertyKey key);
        void GetValue(ref PropertyKey key, IntPtr value);
        void SetValue(ref PropertyKey key, IntPtr value);
        void Commit();
    }

    [ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioEndpointVolume
    {
        void RegisterControlChangeNotify(IntPtr notify);
        void UnregisterControlChangeNotify(IntPtr notify);
        void GetChannelCount(out uint count);
        void SetMasterVolumeLevel(float levelDb, ref Guid ctx);
        void SetMasterVolumeLevelScalar(float level, ref Guid ctx);
        void GetMasterVolumeLevel(out float levelDb);
        void GetMasterVolumeLevelScalar(out float level);
        void SetChannelVolumeLevel(uint channel, float levelDb, ref Guid ctx);
        void SetChannelVolumeLevelScalar(uint channel, float level, ref Guid ctx);
        void GetChannelVolumeLevel(uint channel, out float levelDb);
        void GetChannelVolumeLevelScalar(uint channel, out float level);
        void SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid ctx);
        void GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
        void GetVolumeStepInfo(out uint step, out uint count);
        void VolumeStepUp(ref Guid ctx);
        void VolumeStepDown(ref Guid ctx);
        void QueryHardwareSupport(out uint mask);
        void GetVolumeRange(out float min, out float max, out float inc);
    }

    [ComImport, Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioSessionManager2
    {
        void GetAudioSessionControl(ref Guid groupId, uint flags, out IAudioSessionControl control);
        void GetSimpleAudioVolume(ref Guid groupId, uint flags, out ISimpleAudioVolume volume);
        void GetSessionEnumerator(out IAudioSessionEnumerator sessions);
        void RegisterSessionNotification(IntPtr notify);
        void UnregisterSessionNotification(IntPtr notify);
        void RegisterDuckNotification([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr notify);
        void UnregisterDuckNotification(IntPtr notify);
    }

    [ComImport, Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioSessionEnumerator
    {
        void GetCount(out int count);
        void GetSession(int index, out IAudioSessionControl session);
    }

    [ComImport, Guid("F4B1A599-7266-4319-A8CA-E70ACB11E8CD"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioSessionControl
    {
        void GetState(out int state);
        void GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        void SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string name, ref Guid ctx);
        void GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path);
        void SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string path, ref Guid ctx);
        void GetGroupingParam(out Guid group);
        void SetGroupingParam(ref Guid group, ref Guid ctx);
        void RegisterAudioSessionNotification(IntPtr notify);
        void UnregisterAudioSessionNotification(IntPtr notify);
    }

    [ComImport, Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioSessionControl2
    {
        void Base1(); void Base2(); void Base3(); void Base4(); void Base5(); void Base6(); void Base7(); void Base8(); void Base9();
        void GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
        void GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
        void GetProcessId(out uint pid);
        [PreserveSig] int IsSystemSoundsSession();
        void SetDuckingPreference([MarshalAs(UnmanagedType.Bool)] bool optOut);
    }

    [ComImport, Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ISimpleAudioVolume
    {
        void SetMasterVolume(float level, ref Guid ctx);
        void GetMasterVolume(out float level);
        void SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid ctx);
        void GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
    }

    [ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPolicyConfig
    {
        [PreserveSig] int P1(); [PreserveSig] int P2(); [PreserveSig] int P3(); [PreserveSig] int P4(); [PreserveSig] int P5();
        [PreserveSig] int P6(); [PreserveSig] int P7(); [PreserveSig] int P8(); [PreserveSig] int P9(); [PreserveSig] int P10();
        [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string deviceId, int role);
        [PreserveSig] int SetEndpointVisibility([MarshalAs(UnmanagedType.LPWStr)] string deviceId, int visible);
    }

    class SessionRef
    {
        public ISimpleAudioVolume Vol;
        public Dictionary<string, object> Info;
    }

    public static class Core
    {
        const int CLSCTX_ALL = 23;
        const int STATE_ACTIVE = 1;
        const int STATE_ALL = 15;
        static readonly Guid PKEY_Device = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0");
        static readonly Guid PKEY_Interface = new Guid("026e516e-b814-414b-83cd-856d6fef4822");
        static readonly Guid PKEY_Endpoint = new Guid("1da5d803-d492-4edd-8c23-e0c0ffee7f0e");
        static readonly Regex IdRx = new Regex(@"^\{[0-9]\.[0-9]\.[0-9]\.[0-9]{8}\}\.\{[0-9A-Fa-f\-]{36}\}$");

        [DllImport("ole32.dll")]
        static extern int PropVariantClear(IntPtr pv);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(int access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool QueryFullProcessImageName(IntPtr handle, int flags, StringBuilder text, ref int size);

        // ---------------------------------------------------------------- small helpers
        static string Hex(int hr) { return "0x" + unchecked((uint)hr).ToString("X8"); }
        static int Pct(float f) { return (int)Math.Round(f * 100.0, MidpointRounding.AwayFromZero); }
        static int Clamp(int v) { return Math.Max(0, Math.Min(100, v)); }
        static IMMDeviceEnumerator NewEnum() { return (IMMDeviceEnumerator)(object)new MMDeviceEnumeratorCom(); }
        static Dictionary<string, object> Ok() { Dictionary<string, object> m = new Dictionary<string, object>(); m["ok"] = true; return m; }
        static Dictionary<string, object> Fail(string error, string code)
        {
            Dictionary<string, object> m = new Dictionary<string, object>();
            m["ok"] = false; m["error"] = error; m["code"] = code;
            return m;
        }
        static string Str(Dictionary<string, object> req, string key)
        {
            object v; if (!req.TryGetValue(key, out v) || v == null) return string.Empty; return Convert.ToString(v);
        }
        static int Int(Dictionary<string, object> req, string key)
        {
            object v; if (!req.TryGetValue(key, out v) || v == null) throw new ArgumentException("missing " + key); return Convert.ToInt32(v);
        }
        static bool Bool(Dictionary<string, object> req, string key)
        {
            object v; if (!req.TryGetValue(key, out v) || v == null) throw new ArgumentException("missing " + key); return Convert.ToBoolean(v);
        }
        static string Clean(string s, int max)
        {
            if (s == null) return string.Empty;
            StringBuilder sb = new StringBuilder();
            foreach (char c in s) { if (c >= ' ' && c != (char)127) sb.Append(c); }
            string t = sb.ToString().Trim();
            return t.Length > max ? t.Substring(0, max) : t;
        }

        // ---------------------------------------------------------------- devices
        static string IdOf(IMMDevice d) { string id; d.GetId(out id); return id; }

        static string DefaultId(IMMDeviceEnumerator en, int flow, int role)
        {
            try { IMMDevice d; en.GetDefaultAudioEndpoint(flow, role, out d); return IdOf(d); }
            catch (COMException) { return null; }
        }

        static string PropString(IPropertyStore store, Guid fmt, int pid)
        {
            PropertyKey key = new PropertyKey(); key.fmtid = fmt; key.pid = pid;
            IntPtr pv = Marshal.AllocCoTaskMem(32);
            string result = null;
            try
            {
                for (int i = 0; i < 32; i++) Marshal.WriteByte(pv, i, 0);
                store.GetValue(ref key, pv);
                if (Marshal.ReadInt16(pv) == 31) { IntPtr p = Marshal.ReadIntPtr(pv, 8); if (p != IntPtr.Zero) result = Marshal.PtrToStringUni(p); }
                PropVariantClear(pv);
            }
            catch (COMException) { result = null; }
            finally { Marshal.FreeCoTaskMem(pv); }
            return result;
        }

        static int PropInt(IPropertyStore store, Guid fmt, int pid)
        {
            PropertyKey key = new PropertyKey(); key.fmtid = fmt; key.pid = pid;
            IntPtr pv = Marshal.AllocCoTaskMem(32);
            int result = -1;
            try
            {
                for (int i = 0; i < 32; i++) Marshal.WriteByte(pv, i, 0);
                store.GetValue(ref key, pv);
                if (Marshal.ReadInt16(pv) == 19) result = Marshal.ReadInt32(pv, 8);
                PropVariantClear(pv);
            }
            catch (COMException) { result = -1; }
            finally { Marshal.FreeCoTaskMem(pv); }
            return result;
        }

        static string NameOf(IMMDevice d)
        {
            try
            {
                IPropertyStore s; d.OpenPropertyStore(0, out s);
                string n = PropString(s, PKEY_Device, 14);
                if (string.IsNullOrEmpty(n)) n = PropString(s, PKEY_Interface, 2);
                return Clean(n, 120);
            }
            catch (COMException) { return string.Empty; }
        }

        static int FormOf(IMMDevice d)
        {
            try { IPropertyStore s; d.OpenPropertyStore(0, out s); return PropInt(s, PKEY_Endpoint, 0); }
            catch (COMException) { return -1; }
        }

        static Dictionary<string, object> Describe(IMMDevice d, int flow, string[] defaults)
        {
            Dictionary<string, object> m = new Dictionary<string, object>();
            string id = IdOf(d); int state; d.GetState(out state);
            m["id"] = id; m["name"] = NameOf(d); m["flow"] = flow == 0 ? "output" : "input";
            m["state"] = state; m["form"] = FormOf(d);
            m["def_console"] = id == defaults[0]; m["def_multimedia"] = id == defaults[1]; m["def_communications"] = id == defaults[2];
            return m;
        }

        static string[] Defaults(IMMDeviceEnumerator en, int flow)
        {
            return new string[] { DefaultId(en, flow, 0), DefaultId(en, flow, 1), DefaultId(en, flow, 2) };
        }

        static List<object> ListDevices(IMMDeviceEnumerator en, int flow, int mask)
        {
            List<object> list = new List<object>();
            string[] defs = Defaults(en, flow);
            IMMDeviceCollection col; en.EnumAudioEndpoints(flow, mask, out col);
            int n; col.GetCount(out n);
            for (int i = 0; i < n; i++)
            {
                IMMDevice d; col.Item(i, out d);
                list.Add(Describe(d, flow, defs));
            }
            return list;
        }

        static IAudioEndpointVolume EndpointVolume(IMMDevice d)
        {
            Guid iid = new Guid("5CDF2C82-841E-4546-9722-0CF74078229A");
            object o; d.Activate(ref iid, CLSCTX_ALL, IntPtr.Zero, out o);
            return (IAudioEndpointVolume)o;
        }

        static bool TryReadEndpoint(IMMDevice d, out int pct, out bool mute, out string code)
        {
            pct = -1; mute = false; code = string.Empty;
            try
            {
                IAudioEndpointVolume ev = EndpointVolume(d);
                float f; ev.GetMasterVolumeLevelScalar(out f); ev.GetMute(out mute);
                pct = Pct(f); return true;
            }
            catch (COMException e) { code = Hex(e.ErrorCode); return false; }
        }

        // ---------------------------------------------------------------- operations
        static Dictionary<string, object> OpState()
        {
            IMMDeviceEnumerator en = NewEnum();
            Dictionary<string, object> res = Ok();
            res["output"] = null; res["input"] = null;
            string[] outDefs = Defaults(en, 0);
            if (outDefs[0] != null)
            {
                IMMDevice d; en.GetDevice(outDefs[0], out d);
                Dictionary<string, object> o = new Dictionary<string, object>();
                o["id"] = outDefs[0]; o["name"] = NameOf(d); o["form"] = FormOf(d);
                int pct; bool mute; string code;
                if (TryReadEndpoint(d, out pct, out mute, out code)) { o["volume"] = pct; o["mute"] = mute; o["volume_error"] = string.Empty; }
                else { o["volume"] = -1; o["mute"] = false; o["volume_error"] = code; }
                res["output"] = o;
            }
            string[] inDefs = Defaults(en, 1);
            if (inDefs[0] != null)
            {
                IMMDevice d2; en.GetDevice(inDefs[0], out d2);
                Dictionary<string, object> i = new Dictionary<string, object>();
                i["id"] = inDefs[0]; i["name"] = NameOf(d2); i["form"] = FormOf(d2);
                res["input"] = i;
            }
            return res;
        }

        static Dictionary<string, object> OpDevices()
        {
            IMMDeviceEnumerator en = NewEnum();
            Dictionary<string, object> res = Ok();
            res["outputs"] = ListDevices(en, 0, STATE_ALL);
            res["inputs"] = ListDevices(en, 1, STATE_ALL);
            return res;
        }

        static Dictionary<string, object> OpVolume(Dictionary<string, object> req)
        {
            string mode = Str(req, "mode"); int value = Int(req, "value");
            if (mode != "set" && mode != "delta") throw new ArgumentException("bad mode");
            if (mode == "set" && (value < 0 || value > 100)) throw new ArgumentException("bad value");
            if (mode == "delta" && (value < -100 || value > 100)) throw new ArgumentException("bad value");
            IMMDeviceEnumerator en = NewEnum();
            IMMDevice d; en.GetDefaultAudioEndpoint(0, 0, out d);
            string id = IdOf(d); string name = NameOf(d);
            IAudioEndpointVolume ev = EndpointVolume(d);
            float f; bool mute; ev.GetMasterVolumeLevelScalar(out f); ev.GetMute(out mute);
            int before = Pct(f);
            int target = Clamp(mode == "set" ? value : before + value);
            if (target != before) { Guid ctx = Guid.Empty; ev.SetMasterVolumeLevelScalar(target / 100.0f, ref ctx); }
            int after = before; bool muteAfter = mute;
            for (int attempt = 0; attempt < 12; attempt++)
            {
                Thread.Sleep(attempt == 0 ? 60 : 120);
                IMMDevice d2; NewEnum().GetDevice(id, out d2);
                string code;
                if (!TryReadEndpoint(d2, out after, out muteAfter, out code)) { after = -1; continue; }
                if (after == target) break;
            }
            Dictionary<string, object> res = Ok();
            res["device"] = name; res["before"] = before; res["target"] = target; res["after"] = after;
            res["mute_before"] = mute; res["mute_after"] = muteAfter;
            return res;
        }

        static Dictionary<string, object> OpMute(Dictionary<string, object> req)
        {
            bool want = Bool(req, "muted");
            IMMDeviceEnumerator en = NewEnum();
            IMMDevice d; en.GetDefaultAudioEndpoint(0, 0, out d);
            string id = IdOf(d); string name = NameOf(d);
            IAudioEndpointVolume ev = EndpointVolume(d);
            bool before; ev.GetMute(out before);
            if (before != want) { Guid ctx = Guid.Empty; ev.SetMute(want, ref ctx); }
            bool after = before; int pct = -1;
            for (int attempt = 0; attempt < 12; attempt++)
            {
                Thread.Sleep(attempt == 0 ? 60 : 120);
                IMMDevice d2; NewEnum().GetDevice(id, out d2);
                string code;
                if (!TryReadEndpoint(d2, out pct, out after, out code)) { after = before; continue; }
                if (after == want) break;
            }
            Dictionary<string, object> res = Ok();
            res["device"] = name; res["mute_before"] = before; res["mute_after"] = after; res["volume"] = pct;
            return res;
        }

        static string ProcName(uint pid)
        {
            if (pid == 0) return string.Empty;
            try { return Process.GetProcessById((int)pid).ProcessName; } catch (Exception) { return string.Empty; }
        }

        static string ProcPath(uint pid)
        {
            if (pid == 0) return string.Empty;
            IntPtr h = IntPtr.Zero;
            try
            {
                h = OpenProcess(0x1000, false, (int)pid);
                if (h == IntPtr.Zero) return string.Empty;
                StringBuilder sb = new StringBuilder(1024); int size = sb.Capacity;
                return QueryFullProcessImageName(h, 0, sb, ref size) ? sb.ToString() : string.Empty;
            }
            catch (Exception) { return string.Empty; }
            finally { if (h != IntPtr.Zero) CloseHandle(h); }
        }

        static List<SessionRef> ScanSessions(IMMDeviceEnumerator en)
        {
            List<SessionRef> all = new List<SessionRef>();
            string defId = DefaultId(en, 0, 0);
            IMMDeviceCollection col; en.EnumAudioEndpoints(0, STATE_ACTIVE, out col);
            int n; col.GetCount(out n);
            for (int i = 0; i < n; i++)
            {
                IMMDevice d; col.Item(i, out d);
                string devId = IdOf(d); string devName = NameOf(d);
                IAudioSessionEnumerator se = null; int cnt = 0;
                try
                {
                    Guid iid = new Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F");
                    object o; d.Activate(ref iid, CLSCTX_ALL, IntPtr.Zero, out o);
                    IAudioSessionManager2 mgr = (IAudioSessionManager2)o;
                    mgr.GetSessionEnumerator(out se); se.GetCount(out cnt);
                }
                catch (COMException) { continue; }
                for (int j = 0; j < cnt; j++)
                {
                    try
                    {
                        IAudioSessionControl c; se.GetSession(j, out c);
                        int st; c.GetState(out st);
                        if (st == 2) continue;
                        IAudioSessionControl2 c2 = (IAudioSessionControl2)c;
                        ISimpleAudioVolume sv = (ISimpleAudioVolume)c;
                        uint pid; c2.GetProcessId(out pid);
                        string inst; c2.GetSessionInstanceIdentifier(out inst);
                        bool sys = c2.IsSystemSoundsSession() == 0;
                        string disp = string.Empty; try { c.GetDisplayName(out disp); } catch (COMException) { disp = string.Empty; }
                        float f; bool m; sv.GetMasterVolume(out f); sv.GetMute(out m);
                        Dictionary<string, object> info = new Dictionary<string, object>();
                        info["id"] = inst; info["device"] = devName; info["device_default"] = devId == defId;
                        info["pid"] = (int)pid; info["process"] = Clean(ProcName(pid), 80); info["path"] = ProcPath(pid);
                        info["display"] = Clean(disp, 80); info["volume"] = Pct(f); info["mute"] = m;
                        info["active"] = st == 1; info["system"] = sys;
                        SessionRef r = new SessionRef(); r.Vol = sv; r.Info = info;
                        all.Add(r);
                    }
                    catch (COMException) { continue; }
                }
            }
            return all;
        }

        static SessionRef FindSession(List<SessionRef> all, string id)
        {
            foreach (SessionRef r in all) { if ((string)r.Info["id"] == id) return r; }
            return null;
        }

        static Dictionary<string, object> OpSessions()
        {
            List<SessionRef> all = ScanSessions(NewEnum());
            List<object> list = new List<object>();
            foreach (SessionRef r in all) list.Add(r.Info);
            Dictionary<string, object> res = Ok();
            res["sessions"] = list;
            return res;
        }

        static Dictionary<string, object> OpSessionSet(Dictionary<string, object> req)
        {
            string mode = Str(req, "mode"); int value = req.ContainsKey("value") && req["value"] != null ? Convert.ToInt32(req["value"]) : 0;
            if (mode != "set" && mode != "delta" && mode != "mute" && mode != "unmute") throw new ArgumentException("bad mode");
            if (mode == "set" && (value < 0 || value > 100)) throw new ArgumentException("bad value");
            if (mode == "delta" && (value < -100 || value > 100)) throw new ArgumentException("bad value");
            IEnumerable raw = req.ContainsKey("targets") ? req["targets"] as IEnumerable : null;
            List<string> targets = new List<string>();
            if (raw != null) { foreach (object o in raw) { if (o != null) targets.Add(Convert.ToString(o)); } }
            if (targets.Count == 0 || targets.Count > 40) throw new ArgumentException("bad targets");

            List<SessionRef> all = ScanSessions(NewEnum());
            Dictionary<string, int> expectVol = new Dictionary<string, int>();
            Dictionary<string, int> beforeVol = new Dictionary<string, int>();
            Dictionary<string, bool> beforeMute = new Dictionary<string, bool>();
            Dictionary<string, string> failed = new Dictionary<string, string>();
            foreach (string t in targets)
            {
                SessionRef r = FindSession(all, t);
                if (r == null) { failed[t] = "not_found"; continue; }
                int cur = (int)r.Info["volume"]; bool curMute = (bool)r.Info["mute"];
                beforeVol[t] = cur; beforeMute[t] = curMute;
                try
                {
                    Guid ctx = Guid.Empty;
                    if (mode == "set" || mode == "delta")
                    {
                        int target = Clamp(mode == "set" ? value : cur + value);
                        expectVol[t] = target;
                        if (target != cur) r.Vol.SetMasterVolume(target / 100.0f, ref ctx);
                    }
                    else
                    {
                        bool want = mode == "mute";
                        if (want != curMute) r.Vol.SetMute(want, ref ctx);
                    }
                }
                catch (COMException e) { failed[t] = Hex(e.ErrorCode); }
            }

            Dictionary<string, SessionRef> fresh = new Dictionary<string, SessionRef>();
            for (int attempt = 0; attempt < 10; attempt++)
            {
                Thread.Sleep(attempt == 0 ? 80 : 120);
                List<SessionRef> again = ScanSessions(NewEnum());
                fresh.Clear();
                bool allGood = true;
                foreach (string t in targets)
                {
                    SessionRef r = FindSession(again, t);
                    if (r == null) continue;
                    fresh[t] = r;
                    if (failed.ContainsKey(t)) continue;
                    if (mode == "set" || mode == "delta") { if ((int)r.Info["volume"] != expectVol[t]) allGood = false; }
                    else { if ((bool)r.Info["mute"] != (mode == "mute")) allGood = false; }
                }
                if (allGood) break;
            }

            List<object> results = new List<object>();
            foreach (string t in targets)
            {
                Dictionary<string, object> m = new Dictionary<string, object>();
                m["id"] = t;
                m["error"] = failed.ContainsKey(t) ? failed[t] : string.Empty;
                m["before"] = beforeVol.ContainsKey(t) ? beforeVol[t] : -1;
                m["mute_before"] = beforeMute.ContainsKey(t) && beforeMute[t];
                m["expected"] = expectVol.ContainsKey(t) ? expectVol[t] : -1;
                m["expected_mute"] = mode == "mute" ? 1 : (mode == "unmute" ? 0 : -1);
                if (fresh.ContainsKey(t)) { m["found_after"] = true; m["after"] = fresh[t].Info["volume"]; m["mute_after"] = fresh[t].Info["mute"]; }
                else { m["found_after"] = false; m["after"] = -1; m["mute_after"] = false; }
                results.Add(m);
            }
            Dictionary<string, object> res = Ok();
            res["results"] = results;
            return res;
        }

        static Dictionary<string, object> OpSetDefault(Dictionary<string, object> req)
        {
            string id = Str(req, "id"); int flow = Str(req, "flow") == "input" ? 1 : 0;
            if (!IdRx.IsMatch(id)) throw new ArgumentException("bad device id");
            IMMDeviceEnumerator en = NewEnum();
            bool active = false;
            IMMDeviceCollection col; en.EnumAudioEndpoints(flow, STATE_ACTIVE, out col);
            int n; col.GetCount(out n);
            for (int i = 0; i < n; i++)
            {
                IMMDevice d; col.Item(i, out d);
                if (string.Equals(IdOf(d), id, StringComparison.OrdinalIgnoreCase)) { active = true; break; }
            }
            if (!active) return Fail("device is not an active endpoint of this kind", "not_active");

            IPolicyConfig pc = (IPolicyConfig)(object)new PolicyConfigClient();
            List<object> hrs = new List<object>();
            for (int role = 0; role < 3; role++)
            {
                int hr = pc.SetDefaultEndpoint(id, role);
                hrs.Add(hr < 0 ? Hex(hr) : "ok");
            }

            string[] actual = null;
            bool c = false, mm = false, co = false;
            for (int attempt = 0; attempt < 20; attempt++)
            {
                Thread.Sleep(attempt == 0 ? 100 : 150);
                actual = Defaults(NewEnum(), flow);
                c = string.Equals(actual[0], id, StringComparison.OrdinalIgnoreCase);
                mm = string.Equals(actual[1], id, StringComparison.OrdinalIgnoreCase);
                co = string.Equals(actual[2], id, StringComparison.OrdinalIgnoreCase);
                if (c && mm && co) break;
            }
            Dictionary<string, object> res = Ok();
            res["console"] = c; res["multimedia"] = mm; res["communications"] = co;
            res["set_results"] = hrs;
            res["actual_console"] = actual[0]; res["actual_multimedia"] = actual[1]; res["actual_communications"] = actual[2];
            return res;
        }

        // ---------------------------------------------------------------- entry point
        public static string Run(string requestJson)
        {
            JavaScriptSerializer ser = new JavaScriptSerializer();
            ser.MaxJsonLength = int.MaxValue;
            Dictionary<string, object> res;
            try
            {
                Dictionary<string, object> req = ser.DeserializeObject(requestJson) as Dictionary<string, object>;
                if (req == null) throw new ArgumentException("bad request");
                switch (Str(req, "op"))
                {
                    case "state": res = OpState(); break;
                    case "devices": res = OpDevices(); break;
                    case "sessions": res = OpSessions(); break;
                    case "volume": res = OpVolume(req); break;
                    case "mute": res = OpMute(req); break;
                    case "session_set": res = OpSessionSet(req); break;
                    case "set_default": res = OpSetDefault(req); break;
                    default: res = Fail("unknown operation", "bad_op"); break;
                }
            }
            catch (COMException e) { res = Fail(e.Message, Hex(e.ErrorCode)); }
            catch (Exception e) { res = Fail(e.GetType().Name + ": " + e.Message, string.Empty); }
            return ser.Serialize(res);
        }
    }
}
"""

_PS_TEMPLATE = r"""
$ErrorActionPreference='Stop'
$src=@'
@@CSHARP@@
'@
$json=''
try{
  Add-Type -AssemblyName System.Web.Extensions
  $web=[System.Web.Script.Serialization.JavaScriptSerializer].Assembly.Location
  Add-Type -ReferencedAssemblies $web -TypeDefinition $src
  $json=[KiraAudio.Core]::Run([string]$env:KIRA_AUDIO_REQ)
}catch{
  $json=(@{ok=$false;stage='powershell';error=[string]$_.Exception.Message;code=''}|ConvertTo-Json -Compress)
}
$ascii=[regex]::Replace($json,'[^\u0000-\u007F]',{param($x) '\u'+([int][char]$x.Value).ToString('x4')})
[Console]::Out.Write($ascii)
"""
_SCRIPT = FixedScript("audio-core", _PS_TEMPLATE.replace("@@CSHARP@@", _CSHARP.strip("\n")))

# ------------------------------------------------------------------------------------------------ error texts
_HR_TEXT = {
    "0x80070490": ("دستگاه صدای فعالی پیدا نشد (دستگاه جدا شده، غیرفعال است یا درایور ندارد).", ERROR),
    "0x80070005": ("ویندوز اجازه‌ی دسترسی به این بخش صدا را نداد (دسترسی رد شد؛ سیاست سیستم یا دسترسی برنامه).", DENIED),
    "0x88890004": ("دستگاه صدا همین حالا بی‌اعتبار/قطع شد (احتمالاً جدا شد یا درایور دوباره راه‌اندازی شد).", ERROR),
    "0x8889000A": ("دستگاه صدا در اختیار برنامه‌ای با حالت انحصاری (Exclusive) است.", ERROR),
    "0x80004001": ("این دستگاه کنترل نرم‌افزاری ولوم را پشتیبانی نمی‌کند (مثلاً بعضی خروجی‌های HDMI / S/PDIF).", ERROR),
    "0x80004002": ("رابط لازم در این نسخه‌ی ویندوز پشتیبانی نمی‌شود.", ERROR),
    "0x80040154": ("رابط لازم در این نسخه‌ی ویندوز ثبت نشده است.", ERROR),
    "0x800706BA": ("سرویس «Windows Audio» (Audiosrv) در دسترس نیست؛ در Services.msc آن را Start کن.", ERROR),
    "0x800706BE": ("ارتباط با سرویس «Windows Audio» قطع شد.", ERROR),
}
_PS_HINTS = (("cannot add type", "Add-Type توسط سیاست امنیتی ویندوز (AppLocker / Constrained Language Mode) بسته است"),
             ("language mode", "PowerShell در Constrained Language Mode است و Add-Type را اجازه نمی‌دهد"),
             ("web.extensions", "کتابخانه‌ی System.Web.Extensions (بخشی از .NET Framework) در دسترس نیست"))


def _explain(data: dict, doing: str) -> ToolError:
    """-> a ToolError carrying the real reason for a failed script result."""
    code = str(data.get("code") or "")
    err = str(data.get("error") or "نامشخص")
    if code in _HR_TEXT:
        text, status = _HR_TEXT[code]
        return ToolError(f"{doing} انجام نشد و چیزی تغییر نکرد: {text} (کد {code})", status)
    if data.get("fatal") or data.get("stage") == "powershell":
        low = err.lower()
        hint = next((h for k, h in _PS_HINTS if k in low), "")
        return ToolError(f"{doing} انجام نشد: اجرای ماژول صدا در PowerShell شکست خورد. {hint + '. ' if hint else ''}جزئیات: {err[:300]}")
    if code == "not_active":
        return ToolError(f"{doing} انجام نشد: این دستگاه الان فعال/متصل نیست.")
    return ToolError(f"{doing} انجام نشد: {err[:300]}" + (f" (کد {code})" if code else ""))


def _call(op: str, doing: str, **params) -> dict:
    """Run one fixed audio operation. Returns the script's data dict or raises ToolError with the REAL reason."""
    if not IS_WIN:
        raise ToolError("کنترل صدا فقط روی ویندوز ممکن است.")
    if op not in _OPS:
        raise ToolError(f"عملیات صدای ناشناخته: {op}", BAD_ARGS)
    req = {"op": op, **params}
    data = run_fixed(_SCRIPT, env={"KIRA_AUDIO_REQ": json.dumps(req, ensure_ascii=True)}, timeout=40, api_name="صدای ویندوز")
    if data.get("cancelled"):
        raise ToolError(str(data.get("error") or f"{doing} با درخواست Stop متوقف شد."), DENIED)
    if not data.get("ok"):
        raise _explain(data, doing)
    return data


# ------------------------------------------------------------------------------------------------ naming helpers
_NORM = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": " ", "\u200f": " ", "‎": " ", "ۀ": "ه", "أ": "ا", "إ": "ا"})


def _norm(text: str) -> str:
    t = str(text or "").lower().translate(_NORM)
    t = re.sub(r"\.exe\b", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z\u0600-\u06ff]+", "", _norm(text))


_FORM_FA = {1: "اسپیکر", 2: "Line", 3: "هدفون", 4: "میکروفون", 5: "هدست", 6: "Handset", 8: "S/PDIF", 9: "HDMI/نمایشگر", 0: "شبکه/ریموت"}
_STATE_FA = {2: "غیرفعال (Disabled)", 4: "حاضر نیست (درایور/سخت‌افزار)", 8: "جدا شده (Unplugged)"}
_GAME_PATH_RX = re.compile(r"\\(?:steamapps\\common|epic games|riot games|gog galaxy\\games|gog games|xboxgames|ea games|ubisoft game launcher\\games|battle\.net|blizzard)\\|\\games\\", re.I)
_BROWSERS = ("chrome", "msedge", "firefox", "opera", "brave", "vivaldi", "iexplore", "arc")
_MUSIC = ("spotify", "itunes", "foobar2000", "aimp", "musicbee", "groove", "applemusic", "deezer", "tidal")
_VIDEO = ("vlc", "potplayer", "mpc-hc", "mpc-be", "mpc-hc64", "wmplayer", "mpv", "video", "movies")
_APP_ALIASES = {
    "مرورگر": _BROWSERS, "browser": _BROWSERS, "کروم": ("chrome",), "chrome": ("chrome",), "فایرفاکس": ("firefox",), "اج": ("msedge",), "edge": ("msedge",),
    "اپرا": ("opera",), "دیسکورد": ("discord",), "اسپاتیفای": ("spotify",), "تلگرام": ("telegram",), "واتساپ": ("whatsapp",), "استیم": ("steam", "steamwebhelper"),
    "زوم": ("zoom",), "اسکایپ": ("skype",), "تیمز": ("teams", "ms-teams"), "موسیقی": _MUSIC, "آهنگ": _MUSIC, "music": _MUSIC, "ویدیو": _VIDEO, "ویدئو": _VIDEO,
    "فیلم": _VIDEO, "video": _VIDEO, "پلیر": _VIDEO + _MUSIC, "player": _VIDEO + _MUSIC,
}
_GAME_WORDS = {"بازی", "بازیها", "بازی ها", "game", "games", "gaming", "گیم"}
_SYSTEM_WORDS = {"صداهای سیستم", "صدای سیستم ویندوز", "system sounds", "notification sounds", "نوتیفیکیشن", "اعلان"}


def _devs(items, flow_name: str):
    return [d for d in items or [] if d.get("flow") == flow_name]


def _active(d: dict) -> bool:
    return int(d.get("state") or 0) == 1


def _device_label(d: dict) -> str:
    form = _FORM_FA.get(int(d.get("form") if d.get("form") is not None else -1))
    return f"{d.get('name') or 'دستگاه بدون نام'}" + (f" ({form})" if form else "")


def _pct(v) -> str:
    return f"{int(v)}٪"


# ------------------------------------------------------------------------------------------------ the tools
class AudioTools:
    """Handlers of the Audio capabilities (declared in winmodules.AudioModule). Every handler returns the REAL, re-read result or raises ToolError."""

    # ---------------------------------------------------------------- system volume
    def get_volume(self, a: dict) -> str:
        with _LOCK:
            data = _call("state", "خواندن وضعیت صدا")
        out, inp = data.get("output"), data.get("input")
        parts = []
        if not out:
            raise ToolError("هیچ دستگاه خروجی صدای فعالی به‌عنوان پیش‌فرض ویندوز پیدا نشد (دستگاه جدا شده، غیرفعال است یا درایور ندارد)."
                            + (f" ورودی پیش‌فرض: «{inp.get('name')}»." if inp else ""))
        if out.get("volume_error"):
            code = str(out["volume_error"])
            reason = _HR_TEXT.get(code, (f"خطای ویندوز {code}", ERROR))[0]
            parts.append(f"خروجی پیش‌فرض «{out.get('name')}» است ولی ولوم آن خوانده نشد: {reason}")
        else:
            parts.append(f"ولوم صدای ویندوز {_pct(out['volume'])} است و Mute {'روشن' if out.get('mute') else 'خاموش'} است (خروجی پیش‌فرض: «{out.get('name')}»).")
            if out.get("mute"):
                parts.append("یعنی الان صدایی شنیده نمی‌شود.")
        parts.append(f"ورودی (میکروفون) پیش‌فرض: «{inp.get('name')}»." if inp else "ورودی پیش‌فرض: هیچ دستگاه ورودی فعالی پیدا نشد.")
        return " ".join(parts)

    def set_volume(self, a: dict) -> str:
        percent = self._percent(a.get("percent"))
        with _LOCK:
            data = _call("volume", "تنظیم ولوم", mode="set", value=percent)
        return self._volume_report(data, percent, "تنظیم")

    def change_volume(self, a: dict) -> str:
        direction = str(a.get("direction") or "").lower()
        if direction not in ("up", "down"):
            raise ToolError("direction باید up یا down باشد.", BAD_ARGS)
        amount = self._amount(a.get("amount", 10))
        with _LOCK:
            data = _call("volume", "تغییر ولوم", mode="delta", value=amount if direction == "up" else -amount)
        return self._volume_report(data, int(data.get("target", -1)), "افزایش" if direction == "up" else "کاهش", amount=amount, direction=direction)

    def _volume_report(self, data: dict, target: int, word: str, amount: int | None = None, direction: str | None = None) -> str:
        before, after, name = int(data.get("before", -1)), int(data.get("after", -1)), data.get("device") or "خروجی پیش‌فرض"
        muted = bool(data.get("mute_after"))
        if after < 0:
            raise ToolError(f"ولوم «{name}» تغییر داده شد ولی بعد از آن دوباره خوانده نشد؛ وضعیت واقعی نامشخص است. دوباره وضعیت را بخوان.")
        if abs(after - target) > TOLERANCE or (target != before and after == before):
            raise ToolError(f"ولوم «{name}» روی {_pct(target)} نشد؛ مقدار واقعی بعد از عملیات {_pct(after)} است (قبلاً {_pct(before)}). "
                            "ممکن است درایور/دستگاه یا برنامه‌ی دیگری آن را کنترل کند.")
        note = " توجه: سیستم هنوز Mute است و صدایی شنیده نمی‌شود." if muted else ""
        if amount is not None and before == after:
            edge = "حداکثر (۱۰۰٪)" if direction == "up" else "حداقل (۰٪)"
            return f"ولوم از قبل روی {edge} بود و بیشتر نمی‌شود؛ تغییری اعمال نشد (مقدار واقعی: {_pct(after)} روی «{name}»).{note}"
        if amount is None and before == after:
            return f"ولوم از قبل روی {_pct(after)} بود؛ تغییری لازم نبود (بررسی واقعی «{name}»).{note}"
        extra = f" (درخواست: {word} {amount} واحد درصد)" if amount is not None else ""
        close = "" if after == target else f" (مقدار دقیق درخواستی {_pct(target)} بود؛ دستگاه {_pct(after)} گزارش می‌دهد)"
        return f"ولوم «{name}» از {_pct(before)} به {_pct(after)} رسید{extra} و بعد از تغییر دوباره بررسی شد.{close}{note}"

    def mute(self, a: dict) -> str:
        return self._mute(True)

    def unmute(self, a: dict) -> str:
        return self._mute(False)

    def _mute(self, want: bool) -> str:
        word = "Mute" if want else "Unmute"
        with _LOCK:
            data = _call("mute", f"{word} کردن صدا", muted=want)
        before, after = bool(data.get("mute_before")), bool(data.get("mute_after"))
        name, vol = data.get("device") or "خروجی پیش‌فرض", int(data.get("volume", -1))
        if after != want:
            raise ToolError(f"{word} انجام نشد؛ وضعیت واقعی بعد از عملیات: Mute {'روشن' if after else 'خاموش'} (دستگاه «{name}»). ممکن است درایور یا برنامه‌ی دیگری آن را کنترل کند.")
        tail = f" ولوم {_pct(vol)} است." if vol >= 0 else ""
        if before == after:
            return f"سیستم از قبل {'Mute' if want else 'Unmute'} بود؛ تغییری لازم نبود (بررسی واقعی «{name}»).{tail}"
        if want:
            return f"صدای سیستم Mute شد و بعد از عملیات دوباره بررسی شد (خروجی «{name}»).{tail}"
        warn = " توجه: ولوم ۰٪ است؛ برای شنیدن صدا ولوم را هم بالا ببر." if vol == 0 else ""
        return f"Mute برداشته شد و بعد از عملیات دوباره بررسی شد (خروجی «{name}»).{tail}{warn}"

    # ---------------------------------------------------------------- per-application volume
    def list_apps(self, a: dict) -> str:
        with _LOCK:
            sessions = self._sessions()
        if not sessions:
            return ("هیچ برنامه‌ای در Volume Mixer ویندوز جلسه‌ی صدا ندارد. فقط برنامه‌هایی که صدا پخش می‌کنند یا تازه پخش کرده‌اند دیده می‌شوند؛ "
                    "برنامه‌ی موردنظر را اول پخش کن.")
        groups = self._group(sessions)
        lines = [f"برنامه‌های دارای جلسه‌ی صدا ({len(groups)}):"]
        for g in groups[:25]:
            vols = sorted({int(s["volume"]) for s in g["sessions"]})
            vol_txt = _pct(vols[0]) if len(vols) == 1 else f"{_pct(vols[0])} تا {_pct(vols[-1])}"
            tags = []
            if any(s.get("active") for s in g["sessions"]):
                tags.append("در حال پخش")
            if all(s.get("mute") for s in g["sessions"]):
                tags.append("Mute")
            if g["game"]:
                tags.append("احتمالاً بازی")
            if len(g["sessions"]) > 1:
                tags.append(f"{len(g['sessions'])} جلسه")
            dev = {s["device"] for s in g["sessions"]}
            if not any(s.get("device_default") for s in g["sessions"]):
                tags.append("روی دستگاهی غیر از پیش‌فرض: " + "، ".join(sorted(dev)))
            lines.append(f"- {g['label']} · {vol_txt}" + (" · " + " · ".join(tags) if tags else ""))
        if len(groups) > 25:
            lines.append(f"... و {len(groups) - 25} برنامه‌ی دیگر")
        return "\n".join(lines)

    def set_app_volume(self, a: dict) -> str:
        percent = self._percent(a.get("percent"))
        with _LOCK:
            group = self._pick_app(a.get("app"))
            data = _call("session_set", "تنظیم ولوم برنامه", mode="set", value=percent, targets=[s["id"] for s in group["sessions"]])
        return self._app_report(group, data, "تنظیم")

    def change_app_volume(self, a: dict) -> str:
        direction = str(a.get("direction") or "").lower()
        if direction not in ("up", "down"):
            raise ToolError("direction باید up یا down باشد.", BAD_ARGS)
        amount = self._amount(a.get("amount", 10))
        with _LOCK:
            group = self._pick_app(a.get("app"))
            data = _call("session_set", "تغییر ولوم برنامه", mode="delta", value=amount if direction == "up" else -amount,
                         targets=[s["id"] for s in group["sessions"]])
        return self._app_report(group, data, "افزایش" if direction == "up" else "کاهش", amount=amount)

    def set_app_mute(self, a: dict) -> str:
        muted = a.get("muted")
        if not isinstance(muted, bool):
            raise ToolError("muted باید true یا false باشد.", BAD_ARGS)
        with _LOCK:
            group = self._pick_app(a.get("app"))
            data = _call("session_set", "Mute کردن برنامه" if muted else "Unmute کردن برنامه", mode="mute" if muted else "unmute",
                         targets=[s["id"] for s in group["sessions"]])
        return self._app_report(group, data, "Mute" if muted else "Unmute", mute_want=muted)

    def _app_report(self, group: dict, data: dict, word: str, amount: int | None = None, mute_want: bool | None = None) -> str:
        label = group["label"]
        results = data.get("results") or []
        bad, finals, unchanged = [], [], 0
        for r in results:
            err = str(r.get("error") or "")
            if err:
                bad.append(_HR_TEXT.get(err, ("برنامه یا جلسه پیدا نشد/دیگر وجود ندارد" if err == "not_found" else f"خطای ویندوز {err}", ERROR))[0])
                continue
            if not r.get("found_after"):
                bad.append("جلسه‌ی صدا بعد از تغییر دیگر وجود نداشت (برنامه بسته شد یا پخش را تمام کرد)")
                continue
            if mute_want is not None:
                if bool(r.get("mute_after")) != mute_want:
                    bad.append(f"Mute واقعی بعد از عملیات {'روشن' if r.get('mute_after') else 'خاموش'} است")
                    continue
                if bool(r.get("mute_before")) == mute_want:
                    unchanged += 1
            else:
                exp, after = int(r.get("expected", -1)), int(r.get("after", -1))
                if abs(after - exp) > TOLERANCE or (exp != int(r.get("before", -1)) and after == int(r.get("before", -1))):
                    bad.append(f"ولوم واقعی {_pct(after)} ماند (درخواستی {_pct(exp)})")
                    continue
                if int(r.get("before", -1)) == after:
                    unchanged += 1
                finals.append(after)
        if bad:
            ok_n = len(results) - len(bad)
            raise ToolError(f"«{label}»: {word} کامل انجام نشد ({ok_n} از {len(results)} جلسه موفق). علت: " + " | ".join(dict.fromkeys(bad)) + ".")
        if mute_want is not None:
            if unchanged == len(results):
                return f"«{label}» از قبل {'Mute' if mute_want else 'Unmute'} بود؛ تغییری لازم نبود (بررسی واقعی)."
            return f"«{label}» {'Mute' if mute_want else 'Unmute'} شد و بعد از عملیات دوباره بررسی شد."
        vols = sorted(set(finals))
        shown = _pct(vols[0]) if len(vols) == 1 else f"{_pct(vols[0])} تا {_pct(vols[-1])}"
        sessions = f" ({len(results)} جلسه)" if len(results) > 1 else ""
        if amount is not None and unchanged == len(results):
            return f"ولوم «{label}» از قبل در حد نهایی بود و بیشتر تغییر نمی‌کند؛ مقدار واقعی: {shown}{sessions}."
        extra = f" ({word} {amount} واحد درصد)" if amount is not None else ""
        muted = any(bool(r.get("mute_after")) for r in results)
        note = " توجه: این برنامه Mute است و صدایی از آن شنیده نمی‌شود." if muted else ""
        return f"ولوم «{label}» روی {shown} است{extra}{sessions} و بعد از تغییر دوباره بررسی شد.{note}"

    # ---------------------------------------------------------------- session helpers
    @staticmethod
    def _sessions() -> list:
        data = _call("sessions", "خواندن برنامه‌های دارای صدا")
        out = []
        for s in data.get("sessions") or []:
            s = dict(s)
            path = str(s.pop("path", "") or "")
            s["game"] = bool(_GAME_PATH_RX.search(path))                 # the path is used only for this flag, never shown or returned
            out.append(s)
        return out

    @staticmethod
    def _key(s: dict) -> str:
        if s.get("system"):
            return "system sounds"
        return s.get("process") or s.get("display") or f"pid {s.get('pid')}"

    def _group(self, sessions: list) -> list:
        groups: dict[str, dict] = {}
        for s in sessions:
            key = _norm(self._key(s))
            g = groups.setdefault(key, {"key": key, "label": "", "sessions": [], "game": False})
            g["sessions"].append(s)
            g["game"] = g["game"] or s.get("game", False)
        for g in groups.values():
            first = g["sessions"][0]
            if first.get("system"):
                g["label"] = "صداهای سیستم (System sounds)"
            else:
                proc, disp = first.get("process") or "", first.get("display") or ""
                g["label"] = proc + (f" ({disp})" if disp and _squash(disp) != _squash(proc) and not disp.startswith("@") else "") or f"pid {first.get('pid')}"
        return sorted(groups.values(), key=lambda g: (not any(s.get("active") for s in g["sessions"]), g["label"].lower()))

    def _pick_app(self, query) -> dict:
        """Resolve the user's words ('Discord', 'مرورگر', 'بازی') to ONE application group of live sessions, or raise a clear error."""
        q = _norm(query)
        if not q:
            raise ToolError("نام برنامه مشخص نیست. بپرس کدام برنامه، یا audio_list_apps را بزن.", BAD_ARGS)
        sessions = self._sessions()
        groups = self._group(sessions)
        if not groups:
            raise ToolError("هیچ برنامه‌ای جلسه‌ی صدا ندارد؛ برنامه باید حداقل یک بار صدا پخش کرده باشد تا در Volume Mixer دیده شود. چیزی تغییر نکرد.")
        names = "، ".join(g["label"] for g in groups[:12])
        if q in _GAME_WORDS:
            hits = [g for g in groups if g["game"]]
            if not hits:
                raise ToolError(f"برنامه‌ی «بازی» با جلسه‌ی صدا پیدا نشد (بازی باید در حال اجرا باشد و صدا پخش کرده باشد). برنامه‌های دارای صدا: {names}. اگر بازی در این فهرست است نامش را بپرس یا نام را بگو.")
        elif q in _SYSTEM_WORDS:
            hits = [g for g in groups if g["key"] == "system sounds"]
        else:
            tokens = {_squash(t) for t in _APP_ALIASES.get(q, ())} or {_squash(q)}
            tokens.discard("")
            hits = []
            for g in groups:
                hay = _squash(g["key"]) + "|" + "|".join(_squash(s.get("display", "")) for s in g["sessions"])
                proc = _squash(g["key"])
                if any(t in hay or (len(proc) >= 4 and proc in t) for t in tokens):
                    hits.append(g)
        if not hits:
            raise ToolError(f"برنامه‌ای شبیه «{query}» در Volume Mixer نیست و چیزی تغییر نکرد. برنامه‌های دارای صدا: {names}.")
        if len(hits) > 1:
            exact = [g for g in hits if g["key"] == q or _squash(g["key"]) == _squash(q)]
            if len(exact) == 1:
                return exact[0]
            raise ToolError("چند برنامه با این نام/نوع هستند و چیزی تغییر نکرد؛ از کاربر بپرس کدام را می‌خواهد: " + "، ".join(g["label"] for g in hits[:8]) + ".")
        return hits[0]

    # ---------------------------------------------------------------- devices
    def list_devices(self, a: dict) -> str:
        kind = str(a.get("kind") or "all").lower()
        if kind not in ("all", "output", "input"):
            raise ToolError("kind باید output، input یا all باشد.", BAD_ARGS)
        with _LOCK:
            data = _call("devices", "خواندن فهرست دستگاه‌های صدا")
        outs, ins = data.get("outputs") or [], data.get("inputs") or []
        for d in outs:
            d["flow"] = "output"
        for d in ins:
            d["flow"] = "input"
        lines = []
        cur_out = next((d for d in outs if d.get("def_console") and _active(d)), None)
        cur_in = next((d for d in ins if d.get("def_console") and _active(d)), None)
        if kind in ("all", "output"):
            lines.append("خروجی پیش‌فرض فعلی: " + (f"«{cur_out['name']}»" if cur_out else "ندارد (هیچ دستگاه خروجی فعالی پیش‌فرض نیست)") + ".")
        if kind in ("all", "input"):
            lines.append("ورودی پیش‌فرض فعلی: " + (f"«{cur_in['name']}»" if cur_in else "ندارد (هیچ دستگاه ورودی فعالی پیش‌فرض نیست)") + ".")
        for title, items, show in (("دستگاه‌های خروجی فعال", outs, kind in ("all", "output")), ("دستگاه‌های ورودی فعال", ins, kind in ("all", "input"))):
            if not show:
                continue
            act = [d for d in items if _active(d)]
            lines.append(f"{title} ({len(act)}):" if act else f"{title}: هیچ")
            for d in act:
                tags = []
                if d.get("def_console"):
                    tags.append("پیش‌فرض")
                if d.get("def_communications") and not d.get("def_console"):
                    tags.append("پیش‌فرض ارتباطات (تماس‌ها)")
                lines.append(f"- {_device_label(d)}" + (f" [{'، '.join(tags)}]" if tags else ""))
            gone = [d for d in items if not _active(d)]
            if gone:
                lines.append("  غیرفعال یا جدا شده: " + "؛ ".join(f"{_device_label(d)} — {_STATE_FA.get(int(d.get('state') or 0), 'نامشخص')}" for d in gone[:10]))
        return "\n".join(lines)

    def set_default_device(self, a: dict) -> str:
        kind = str(a.get("kind") or "").lower()
        if kind not in ("output", "input"):
            raise ToolError("kind باید output (خروجی) یا input (ورودی) باشد.", BAD_ARGS)
        query = str(a.get("device") or "").strip()
        if not query:
            raise ToolError("نام یا نوع دستگاه مشخص نیست؛ از کاربر بپرس یا audio_list_devices را بزن.", BAD_ARGS)
        label = "خروجی" if kind == "output" else "ورودی"
        with _LOCK:
            listing = _call("devices", f"خواندن فهرست دستگاه‌ها برای تغییر {label}")
            items = _devs([{**d, "flow": "output"} for d in listing.get("outputs") or []] + [{**d, "flow": "input"} for d in listing.get("inputs") or []], kind)
            target = self._pick_device(query, items, label)
            if not _ID_RX.match(str(target.get("id") or "")):
                raise ToolError("شناسه‌ی دستگاه از ویندوز معتبر برنامه‌ریزی نشده است؛ چیزی تغییر نکرد.")
            if target.get("def_console") and target.get("def_multimedia") and target.get("def_communications"):
                return f"«{target['name']}» از قبل {label} پیش‌فرض ویندوز بود؛ تغییری لازم نبود (بررسی واقعی: Console، Multimedia و Communications)."
            data = _call("set_default", f"تغییر {label} پیش‌فرض", id=target["id"], flow=kind)
        by_id = {str(d.get("id")).lower(): d for d in items}

        def who(key: str) -> str:
            d = by_id.get(str(data.get(key) or "").lower())
            return f"«{d['name']}»" if d else "دستگاه دیگر/هیچ"
        c, m, co = bool(data.get("console")), bool(data.get("multimedia")), bool(data.get("communications"))
        if not (c and m):
            fails = [str(x) for x in data.get("set_results") or [] if str(x) != "ok"]
            why = ""
            if fails:
                why = " علت: " + " | ".join(dict.fromkeys(_HR_TEXT.get(x, (f"خطای ویندوز {x}", ERROR))[0] for x in fails)) + "."
            raise ToolError(f"{label} پیش‌فرض «{target['name']}» نشد. وضعیت واقعی بعد از عملیات: Console = {who('actual_console')}، Multimedia = {who('actual_multimedia')}.{why}"
                            " (ویندوز یا درایور تغییر را نپذیرفت؛ می‌شود از Settings ← System ← Sound دستی انتخاب کرد.)")
        extra = "" if co else f" (نقش Communications هنوز روی {who('actual_communications')} است.)"
        return f"{label} پیش‌فرض ویندوز اکنون «{target['name']}» است و بعد از تغییر دوباره بررسی شد (Console ✓، Multimedia ✓، Communications {'✓' if co else '✗'}).{extra}"

    @staticmethod
    def _pick_device(query: str, items: list, label: str) -> dict:
        """Resolve the user's words ('هدفون', 'Realtek', full name) to ONE active device or raise a clear error. Never guesses between several."""
        q = _norm(query)
        qs = _squash(query)
        active = [d for d in items if _active(d)]
        gone = [d for d in items if not _active(d)]
        listing = "، ".join(_device_label(d) for d in active) or "هیچ دستگاه فعالی نیست"

        def pick(cands: list):
            if len(cands) == 1:
                return cands[0]
            if len(cands) > 1:
                raise ToolError(f"چند {label} با «{query}» می‌خواند و چیزی تغییر نکرد؛ از کاربر بپرس کدام: " + "، ".join(_device_label(d) for d in cands[:8]) + ".")
            return None
        exact = [d for d in active if _norm(d.get("name")) == q]
        found = pick(exact)
        if found:
            return found
        sub = [d for d in active if qs and qs in _squash(d.get("name"))]
        found = pick(sub)
        if found:
            return found
        hp = ((3, 5), ("headphone", "earphone", "airpods", "buds", "هدفون"))
        hs = ((5, 3), ("headset", "handsfree", "هدست"))
        sp = ((1,), ("speaker", "اسپیکر", "بلندگو"))
        hd = ((9,), ("hdmi", "monitor", "display", "nvidia", "tv"))
        mc = ((4,), ("microphone", "mic", "میکروفون"))
        kinds = {"هدفون": hp, "headphones": hp, "headphone": hp, "ایرفون": hp, "ایرپاد": hp, "earphones": hp, "earbuds": hp, "هدست": hs, "headset": hs,
                 "اسپیکر": sp, "بلندگو": sp, "speaker": sp, "speakers": sp, "مانیتور": hd, "تلویزیون": hd, "hdmi": hd, "tv": hd, "monitor": hd,
                 "میکروفون": mc, "میکروفن": mc, "میک": mc, "microphone": mc, "mic": mc}
        words = [w for w in re.split(r"[\s،,]+", q) if w]
        form_hit = next((kinds[w] for w in words if w in kinds), None) or kinds.get(q)
        if form_hit:
            forms, tokens = form_hit
            cands = [d for d in active if int(d.get("form") if d.get("form") is not None else -1) in forms or any(t in _squash(d.get("name")) for t in tokens)]
            if len(cands) > 1:                                       # prefer the type the user named first (e.g. headphones before headset)
                strict = [d for d in cands if int(d.get("form") if d.get("form") is not None else -1) == forms[0]]
                cands = strict if len(strict) == 1 else cands
            found = pick(cands)
            if found:
                return found
        hint = ""
        near = [d for d in gone if qs and (qs in _squash(d.get("name")))]
        if near:
            hint = f" «{near[0]['name']}» در ویندوز ثبت است ولی الان {_STATE_FA.get(int(near[0].get('state') or 0), 'فعال نیست')}؛ اول دستگاه را وصل/فعال کن."
        raise ToolError(f"{label}ی با نام یا نوع «{query}» پیدا نشد و چیزی تغییر نکرد.{hint} دستگاه‌های فعال: {listing}.")

    # ---------------------------------------------------------------- arguments
    @staticmethod
    def _percent(value) -> int:
        try:
            p = int(value)
        except (TypeError, ValueError):
            raise ToolError("درصد ولوم باید عدد صحیح ۰ تا ۱۰۰ باشد.", BAD_ARGS)
        if not 0 <= p <= 100:
            raise ToolError(f"درصد ولوم باید بین ۰ و ۱۰۰ باشد (دریافت شد: {p}). چیزی تغییر نکرد.", BAD_ARGS)
        return p

    @staticmethod
    def _amount(value) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ToolError("مقدار تغییر باید عدد صحیح ۱ تا ۱۰۰ باشد.", BAD_ARGS)
        if not 1 <= n <= 100:
            raise ToolError(f"مقدار تغییر باید بین ۱ و ۱۰۰ باشد (دریافت شد: {n}). چیزی تغییر نکرد.", BAD_ARGS)
        return n
