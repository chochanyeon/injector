Option Explicit
Dim shell, files, root, python, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = "pythonw.exe"
If files.FileExists(root & "\.venv\Scripts\pythonw.exe") Then python = root & "\.venv\Scripts\pythonw.exe"
command = """" & python & """ """ & root & "\injector.py"" serve --open"
shell.CurrentDirectory = root
On Error Resume Next
result = shell.Run(command, 0, True)
If Err.Number <> 0 Then
  MsgBox "Python could not be started. Install Python and see README.md.", vbExclamation, "Injector"
ElseIf result <> 0 Then
  MsgBox "Injector could not start. Check Python dependencies and port 18770. See README.md.", vbExclamation, "Injector"
End If
