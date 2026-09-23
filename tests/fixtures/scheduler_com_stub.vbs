' Test-only COM substitute. Both the user's 0.3.2 bridge and the current bridge
' load exactly the same program text and server assignments from a fake EGP.
Class EmptyResults
  Public Property Get Count
    Count = 0
  End Property
End Class
Class LogStub
  Public Sub SaveAs(path)
    Dim output, config
    Set config = ReadProjectConfig()
    If config.documentElement.getAttribute("log_error") = "1" Then Err.Raise 7002, , "Simulated log save failure"
    Set output = CreateObject("Scripting.FileSystemObject").CreateTextFile(path, True)
    output.Write config.documentElement.getAttribute("log")
    output.Close
  End Sub
End Class
Class CodeStub
  Public Name, Text, Server, UseApplicationOptions, Results, OutputDatasets, Log
  Private Sub Class_Initialize
    Set Results = New EmptyResults
    Set OutputDatasets = New EmptyResults
    Set Log = New LogStub
    Server = "WRONG_DEFAULT_SERVER"
  End Sub
  Public Sub Run
    Dim config, output, folder, filesystem
    Set filesystem = CreateObject("Scripting.FileSystemObject")
    Set config = ReadProjectConfig()
    ' Logs are always inside the task folder; a runner template can live elsewhere.
    folder = filesystem.GetParentFolderName(filesystem.GetParentFolderName(logPath))
    If Server <> config.documentElement.getAttribute("expected_server") Then Err.Raise 7001, , "Source SAS server was not assigned"
    If CreateObject("WScript.Shell").CurrentDirectory <> folder Then Err.Raise 7003, , "Task did not run in its own directory"
    Set output = filesystem.CreateTextFile(folder & "\executed.txt", False)
    output.Write Server
    output.Close
    If config.documentElement.getAttribute("delay") <> "" Then WScript.Sleep CLng(config.documentElement.getAttribute("delay"))
    If config.documentElement.getAttribute("run_error") = "1" Then Err.Raise 7004, , "Simulated execution failure"
  End Sub
End Class
Class CollectionStub
  Private entries(100), total
  Private Sub Class_Initialize
    total = 0
  End Sub
  Public Function Add
    Dim entry
    Set entry = New CodeStub
    Set entries(total) = entry
    total = total + 1
    Set Add = entry
  End Function
  Public Function Item(index)
    Set Item = entries(index)
  End Function
  Public Property Get Count
    Count = total
  End Property
  Public Property Get AllItems
    Dim answer(), i
    ReDim answer(total - 1)
    For i = 0 To total - 1
      Set answer(i) = entries(i)
    Next
    AllItems = answer
  End Property
End Class
Class ProjectStub
  Public CodeCollection
  Private Sub Class_Initialize
    Set CodeCollection = New CollectionStub
  End Sub
  Public Sub Close
  End Sub
End Class
Function ReadProjectConfig()
  Dim config
  Set config = CreateObject("MSXML2.DOMDocument.6.0")
  config.async = False
  config.preserveWhiteSpace = True
  If Not config.Load(projectPath) Then Err.Raise 7005, , "Invalid test fixture"
  Set ReadProjectConfig = config
End Function
Class ApplicationStub
  Public Function Open(path, password)
    Dim result, entry, config, node
    Set config = ReadProjectConfig()
    Set result = New ProjectStub
    For Each node In config.selectNodes("/project/program")
      Set entry = result.CodeCollection.Add
      entry.Name = node.getAttribute("name")
      entry.Text = node.Text
      entry.Server = node.getAttribute("server")
    Next
    Set Open = result
  End Function
  Public Sub Quit
  End Sub
End Class
