' Test-only EG objects. Real Windows cscript, ADODB, XML and process IO remain.
Function Config()
  Dim doc
  Set doc = CreateObject("MSXML2.DOMDocument.6.0")
  doc.async = False
  If Not doc.Load(projectPath) Then Err.Raise 7001, , "Cannot read test EGP"
  Set Config = doc.documentElement
End Function

Sub WriteUtf8(path, contents)
  Dim output
  Set output = CreateObject("ADODB.Stream")
  output.Type = 2
  output.Charset = "utf-8"
  output.Open
  output.WriteText contents
  output.SaveToFile path, 2
  output.Close
End Sub

Class LogStub
  Public Sub SaveAs(path)
    Dim settings
    Set settings = Config()
    If settings.getAttribute("log_error") = "1" Then Err.Raise 7002, , "Simulated log save failure"
    WriteUtf8 path, settings.getAttribute("log")
  End Sub
End Class

Class OutputStub
  Public Name, Kind, Broken
  Public Sub SaveAs(path)
    Dim filesystem, settings
    If Broken Then Err.Raise 7003, , "Access denied"
    Set filesystem = CreateObject("Scripting.FileSystemObject")
    Set settings = Config()
    If Kind = "html" Then
      WriteUtf8 path, "<!doctype html><html><body>sample report</body></html>"
    ElseIf Right(path, 5) = ".xlsx" Then
      filesystem.CopyFile settings.getAttribute("workbook"), path
    Else
      WriteUtf8 path, "id,name" & vbLf & "1,caf" & ChrW(233)
    End If
  End Sub
End Class

Class CollectionStub
  Private entries(100), total
  Private Sub Class_Initialize
    total = 0
  End Sub
  Public Function Add
    Dim item
    Set item = New CodeStub
    Set entries(total) = item
    total = total + 1
    Set Add = item
  End Function
  Public Sub AddOutput(kind, name, broken)
    Dim item
    Set item = New OutputStub
    item.Name = name
    item.Kind = kind
    item.Broken = broken
    Set entries(total) = item
    total = total + 1
  End Sub
  Public Function Item(index)
    Set Item = entries(index)
  End Function
  Public Property Get Count
    Count = total
  End Property
  Public Property Get AllItems
    Dim result(), i
    ReDim result(total - 1)
    For i = 0 To total - 1
      Set result(i) = entries(i)
    Next
    AllItems = result
  End Property
End Class

Class CodeStub
  Public Name, Text, Server, UseApplicationOptions, GenHTML, GenListing, GenSasReport, GenPDF, GenRTF
  Public Log, Results, OutputDatasets
  Private Sub Class_Initialize
    Set Log = New LogStub
    Set Results = New CollectionStub
    Set OutputDatasets = New CollectionStub
    Name = ""
    Server = "WRONG_DEFAULT_SERVER"
  End Sub
  Public Sub Run
    Dim settings, filesystem
    Set settings = Config()
    Set filesystem = CreateObject("Scripting.FileSystemObject")
    If Name <> "" Then Err.Raise 7004, , "An existing project program was executed"
    If Server <> settings.getAttribute("expected_server") Then Err.Raise 7005, , "Wrong SAS server"
    If CreateObject("WScript.Shell").CurrentDirectory <> outDir Then Err.Raise 7006, , "Wrong working folder"
    If UseApplicationOptions Or GenListing Or GenSasReport Or GenPDF Or GenRTF Then Err.Raise 7007, , "Output formats were not configured"
    WriteUtf8 outDir & "\executed.sas", Text
    If GenHTML Then
      Results.AddOutput "html", "HTML: report", False
      Results.AddOutput "html", "HTML? report", False
    End If
    OutputDatasets.AddOutput "table", "WORK:sample", (settings.getAttribute("fail_first_table") = "1")
    OutputDatasets.AddOutput "table", "WORK?sample", False
    If settings.getAttribute("delay") <> "" Then WScript.Sleep CLng(settings.getAttribute("delay"))
    If settings.getAttribute("run_error") = "1" Then Err.Raise 7008, , "Simulated code.Run failure"
  End Sub
End Class

Class ProjectStub
  Public CodeCollection
  Private Sub Class_Initialize
    Set CodeCollection = New CollectionStub
  End Sub
  Public Sub Close
    WriteUtf8 outDir & "\closed.txt", "Closed without saving the EGP"
  End Sub
End Class

Class ApplicationStub
  Public Function Open(path, password)
    Dim settings, result, entry, node
    Set settings = Config()
    Set result = New ProjectStub
    For Each node In settings.selectNodes("program")
      Set entry = result.CodeCollection.Add
      entry.Name = node.getAttribute("name")
      entry.Server = node.getAttribute("server")
    Next
    Set Open = result
  End Function
  Public Sub Quit
    WriteUtf8 outDir & "\quit.txt", "Own automation instance closed"
  End Sub
End Class
