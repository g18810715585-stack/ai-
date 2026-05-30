Option Explicit

Dim shell
Dim nodeExe
Dim workDir
Dim command

Set shell = CreateObject("WScript.Shell")
nodeExe = WScript.Arguments(0)
workDir = WScript.Arguments(1)

shell.CurrentDirectory = workDir
command = """" & nodeExe & """ src\cli.mjs server --port 4321"
shell.Run command, 0, False

