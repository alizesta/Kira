"""Fixed Windows PowerShell/C# implementation of the Core Audio operations.

Keep the native interop script separate from Python tool orchestration so the
Audio handlers remain small and the script is reviewed as one immutable unit.
"""
from .winrunner import FixedScript


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
AUDIO_SCRIPT = FixedScript("audio-core", _PS_TEMPLATE.replace("@@CSHARP@@", _CSHARP.strip("\n")))
