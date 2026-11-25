Option Explicit

Dim shell, fso, scriptDir, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(scriptDir, "start_kira.bat")

If Not fso.FileExists(launcher) Then
    MsgBox "Kira launcher was not found:" & vbCrLf & launcher, vbCritical, "Project Kira"
    WScript.Quit 1
End If

shell.CurrentDirectory = scriptDir
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "autostart" Then shell.Environment("Process")("KIRA_AUTOSTART") = "1"
End If
shell.Run """" & launcher & """", 0, False
