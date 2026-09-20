' Windows double-click launcher. Runs run.bat from this folder.
' Nicer name than run.bat; first run installs, later runs just open the app.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
folder  = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = folder
sh.Run """" & folder & "\run.bat""", 1, False
