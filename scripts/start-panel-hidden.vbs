Option Explicit

Dim shell
Dim nodeExe
Dim workDir
Dim command
Dim outLog
Dim errLog

Set shell = CreateObject("WScript.Shell")
nodeExe = WScript.Arguments(0)
workDir = WScript.Arguments(1)
outLog = workDir & ".runs\panel-4321.out.log"
errLog = workDir & ".runs\panel-4321.err.log"

shell.CurrentDirectory = workDir
command = "%ComSpec% /d /c " & Chr(34) & Chr(34) & nodeExe & Chr(34) & " src\cli.mjs server --port 4321 >> " & Chr(34) & outLog & Chr(34) & " 2>> " & Chr(34) & errLog & Chr(34) & Chr(34)
shell.Run command, 0, False
