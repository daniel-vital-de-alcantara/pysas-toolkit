Option Explicit

Dim fso, shell, workingFolder
Dim projectName, programName, rangeText, stopProgramText, taskLabel, sectionName, manifestName
Dim projectPath, logPath, codePath, manifestPath
Dim egApp, project, sasProgram, codeToRun
Dim exitCode, stopProgramOnError
Dim targetText, submittedText, initText

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
workingFolder = shell.CurrentDirectory
exitCode = 0
stopProgramOnError = False

If WScript.Arguments.Count <> 7 Then
    WScript.Echo "ERROR: Expected project, program, range, stop_program_on_error, task label, section, always-run manifest."
    WScript.Quit 10
End If

projectName = Trim(WScript.Arguments(0))
programName = Trim(WScript.Arguments(1))
rangeText = Trim(WScript.Arguments(2))
stopProgramText = Trim(WScript.Arguments(3))
taskLabel = Trim(WScript.Arguments(4))
sectionName = Trim(WScript.Arguments(5))
manifestName = Trim(WScript.Arguments(6))

If sectionName <> "" And rangeText <> "" Then
    WScript.Echo "ERROR: Specify either section or row range, not both."
    WScript.Quit 23
End If
If stopProgramText <> "0" And stopProgramText <> "1" Then
    WScript.Echo "ERROR: stop_program_on_error must be 0 or 1."
    WScript.Quit 19
End If
stopProgramOnError = (stopProgramText = "1")

projectPath = fso.BuildPath(workingFolder, projectName)
manifestPath = fso.BuildPath(workingFolder, manifestName)
If Not fso.FileExists(projectPath) Then
    WScript.Echo "ERROR: Project not found: " & projectPath
    WScript.Quit 11
End If
If Not fso.FileExists(manifestPath) Then
    WScript.Echo "ERROR: Always-run manifest not found: " & manifestPath
    WScript.Quit 27
End If
EnsureFolder fso.BuildPath(workingFolder, "logs")
EnsureFolder fso.BuildPath(workingFolder, "code")

On Error Resume Next
Set egApp = CreateObject("SASEGObjectModel.Application.8.1")
If Err.Number <> 0 Then
    Err.Clear
    Set egApp = CreateObject("SASEGObjectModel.Application.7.1")
End If
If Err.Number <> 0 Then
    WScript.Echo "ERROR: Could not start Enterprise Guide."
    WScript.Echo Err.Description
    WScript.Quit 12
End If
On Error GoTo 0

WScript.Echo "Enterprise Guide started."
WScript.Echo "Project: " & projectPath
WScript.Echo "Program: " & programName
WScript.Echo "Stop program on SAS error: " & CStr(stopProgramOnError)

On Error Resume Next
Err.Clear
Set project = egApp.Open(projectPath, "")
If Err.Number <> 0 Then
    WScript.Echo "ERROR: Could not open the project."
    WScript.Echo Err.Description
    egApp.Quit
    WScript.Quit 13
End If
On Error GoTo 0

initText = BuildAlwaysRunText(manifestPath)
targetText = GetSelectedText(programName, rangeText, sectionName)

submittedText = "options iomlogautoflush;" & vbCrLf
If stopProgramOnError Then
    submittedText = "options iomlogautoflush errorabend errorcheck=strict;" & vbCrLf
End If
If initText <> "" Then
    submittedText = submittedText & _
        "/* ALWAYS_RUN_INITIALIZATION_START */" & vbCrLf & _
        initText & vbCrLf & _
        "/* ALWAYS_RUN_INITIALIZATION_END */" & vbCrLf
End If
submittedText = submittedText & _
    "/* SCHEDULED_TARGET_START */" & vbCrLf & _
    targetText & vbCrLf & _
    "/* SCHEDULED_TARGET_END */"

Set sasProgram = FindProgram(programName)
Set codeToRun = project.CodeCollection.Add
codeToRun.Text = submittedText
codeToRun.Server = sasProgram.Server

codePath = fso.BuildPath(fso.BuildPath(workingFolder, "code"), taskLabel & ".sas")
WriteTextFile codePath, submittedText
WScript.Echo "Submitted code saved: " & codePath

logPath = fso.BuildPath(fso.BuildPath(workingFolder, "logs"), taskLabel & ".log")
On Error Resume Next
Err.Clear
codeToRun.Run
If Err.Number <> 0 Then
    WScript.Echo "ERROR: Enterprise Guide reported an execution failure."
    WScript.Echo Err.Description
    exitCode = 20
End If
Err.Clear
codeToRun.Log.SaveAs logPath
If Err.Number <> 0 Then
    WScript.Echo "ERROR: Could not save the log."
    WScript.Echo Err.Description
    If exitCode = 0 Then exitCode = 21
Else
    WScript.Echo "Log saved: " & logPath
End If
On Error GoTo 0

If fso.FileExists(logPath) Then
    If LogContainsErrors(logPath) Then
        WScript.Echo "RESULT: SAS ERROR messages were found in the log."
        exitCode = 22
    Else
        WScript.Echo "RESULT: No SAS ERROR messages detected."
    End If
End If

project.Close
egApp.Quit
WScript.Echo "Enterprise Guide closed."
WScript.Quit exitCode

Function BuildAlwaysRunText(filePath)
    Dim inputFile, currentLine, fields, combined, piece
    combined = ""
    Set inputFile = fso.OpenTextFile(filePath, 1, False)
    Do Until inputFile.AtEndOfStream
        currentLine = inputFile.ReadLine
        If Trim(currentLine) <> "" Then
            fields = Split(currentLine, vbTab)
            If UBound(fields) <> 2 Then
                CleanExit "ERROR: Invalid always-run manifest row.", 28
            End If
            piece = GetSelectedText(Trim(fields(0)), Trim(fields(1)), Trim(fields(2)))
            If combined <> "" Then combined = combined & vbCrLf
            combined = combined & _
                "/* ALWAYS_RUN_ITEM: " & Trim(fields(0)) & " */" & vbCrLf & piece
        End If
    Loop
    inputFile.Close
    BuildAlwaysRunText = combined
End Function

Function FindProgram(requestedName)
    Dim item, matchCount, matchedItem
    matchCount = 0
    For Each item In project.CodeCollection
        If LCase(Trim(item.Name)) = LCase(Trim(requestedName)) Then
            matchCount = matchCount + 1
            Set matchedItem = item
        End If
    Next
    If matchCount = 0 Then CleanExit "ERROR: Program not found: " & requestedName, 14
    If matchCount > 1 Then CleanExit "ERROR: Program name is duplicated: " & requestedName, 29
    Set FindProgram = matchedItem
End Function

Function GetSelectedText(requestedName, requestedRange, requestedSection)
    Dim item, textValue
    Set item = FindProgram(requestedName)
    textValue = item.Text
    If requestedSection <> "" Then
        textValue = ExtractSection(textValue, requestedSection)
        WScript.Echo "Always/target section selected: " & requestedSection
    ElseIf requestedRange <> "" Then
        textValue = ExtractRange(textValue, requestedRange)
        WScript.Echo "Always/target range selected: " & requestedRange
    End If
    GetSelectedText = textValue
End Function

Function ExtractSection(textValue, requestedSection)
    Dim normalized, lines, i, startIndex, endIndex, startCount, endCount
    Dim startMarker, endMarker, selected
    normalized = Replace(textValue, vbCrLf, vbLf)
    normalized = Replace(normalized, vbCr, vbLf)
    lines = Split(normalized, vbLf)
    startMarker = LCase("* (please do not delete) section_start: " & requestedSection & ";")
    endMarker = LCase("* (please do not delete) section_end: " & requestedSection & ";")
    startIndex = -1
    endIndex = -1
    startCount = 0
    endCount = 0
    For i = 0 To UBound(lines)
        If LCase(Trim(lines(i))) = startMarker Then
            startCount = startCount + 1
            startIndex = i
        End If
        If LCase(Trim(lines(i))) = endMarker Then
            endCount = endCount + 1
            endIndex = i
        End If
    Next
    If startCount <> 1 Then CleanExit "ERROR: Expected exactly one section_start marker for: " & requestedSection, 24
    If endCount <> 1 Then CleanExit "ERROR: Expected exactly one section_end marker for: " & requestedSection, 25
    If endIndex <= startIndex Then CleanExit "ERROR: Section end must appear after section start: " & requestedSection, 26
    selected = ""
    For i = startIndex + 1 To endIndex - 1
        selected = selected & lines(i)
        If i < endIndex - 1 Then selected = selected & vbCrLf
    Next
    ExtractSection = selected
End Function

Function ExtractRange(textValue, requestedRange)
    Dim parts, normalized, lines, startLine, endLine, totalLines, i, selected
    parts = Split(requestedRange, ":")
    If UBound(parts) <> 1 Then CleanExit "ERROR: Invalid range. Expected 20:45, 20:, or :45", 15
    normalized = Replace(textValue, vbCrLf, vbLf)
    normalized = Replace(normalized, vbCr, vbLf)
    lines = Split(normalized, vbLf)
    totalLines = UBound(lines) + 1
    If Trim(parts(0)) = "" Then
        startLine = 1
    ElseIf IsNumeric(Trim(parts(0))) Then
        startLine = CLng(Trim(parts(0)))
    Else
        CleanExit "ERROR: Start line must be numeric.", 16
    End If
    If Trim(parts(1)) = "" Then
        endLine = totalLines
    ElseIf IsNumeric(Trim(parts(1))) Then
        endLine = CLng(Trim(parts(1)))
    Else
        CleanExit "ERROR: End line must be numeric.", 16
    End If
    If startLine < 1 Or endLine < startLine Then CleanExit "ERROR: Invalid line range: " & requestedRange, 17
    If endLine > totalLines Then CleanExit "ERROR: End line exceeds program length. Program lines: " & totalLines, 18
    selected = ""
    For i = startLine To endLine
        selected = selected & lines(i - 1)
        If i < endLine Then selected = selected & vbCrLf
    Next
    ExtractRange = selected
End Function

Sub EnsureFolder(folderPath)
    If Not fso.FolderExists(folderPath) Then fso.CreateFolder folderPath
End Sub

Sub WriteTextFile(filePath, textValue)
    Dim outputFile
    Set outputFile = fso.CreateTextFile(filePath, True, False)
    outputFile.Write textValue
    outputFile.Close
End Sub

Sub CleanExit(message, code)
    WScript.Echo message
    On Error Resume Next
    project.Close
    egApp.Quit
    On Error GoTo 0
    WScript.Quit code
End Sub

Function LogContainsErrors(filePath)
    Dim textFile, currentLine, trimmedLine
    LogContainsErrors = False
    Set textFile = fso.OpenTextFile(filePath, 1, False)
    Do Until textFile.AtEndOfStream
        currentLine = textFile.ReadLine
        trimmedLine = UCase(Trim(currentLine))
        If Left(trimmedLine, 6) = "ERROR:" Then
            LogContainsErrors = True
            Exit Do
        End If
    Loop
    textFile.Close
End Function
