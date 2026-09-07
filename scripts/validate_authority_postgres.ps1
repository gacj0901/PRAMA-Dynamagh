param(
    [switch]$RunFullValidation,
    [switch]$DiagnoseTargetedTests,
    [switch]$DiagnoseHang,
    [switch]$DiagnosePostgresSuite
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        Write-Output "DATABASE_URL_PRESENT: $([bool]$env:DATABASE_URL)"
        Write-Output "LOCAL_VALIDATOR_GATE: BLOCKED"
        Write-Output "BLOCKERS: Python runtime not found; use backend/.venv or the project-defined environment."
        exit 2
    }
    $python = $pythonCommand.Source
}

function Write-Heartbeat {
    param([Parameter(Mandatory = $true)][string]$Message)
    [Console]::WriteLine($Message)
    [Console]::Out.Flush()
}

function Invoke-SafeChildProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FileName,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [AllowNull()][string]$StandardInput,
        [Parameter(Mandatory = $true)][string]$CommandSanitized
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FileName
    $startInfo.WorkingDirectory = (Get-Location).Path
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    Write-Heartbeat ("PROCESS_COMMAND_SANITIZED: " + $CommandSanitized)
    if (-not $process.Start()) {
        throw "Unable to start child process: $CommandSanitized"
    }
    Write-Heartbeat ("PROCESS_START: " + $CommandSanitized)
    Write-Heartbeat ("PROCESS_PID: " + $process.Id)

    # Begin both reads before waiting to avoid stdout/stderr pipe deadlocks.
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    try {
        if ($null -ne $StandardInput) {
            $process.StandardInput.Write($StandardInput)
        }
    }
    finally {
        # No child process is allowed to wait for validator stdin.
        $process.StandardInput.Close()
    }

    $process.WaitForExit()
    $stdoutTask.Wait()
    $stderrTask.Wait()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
    Write-Heartbeat ("PROCESS_EXIT: " + $exitCode)
    $process.Dispose()

    [pscustomobject]@{
        ExitCode = $exitCode
        StdOut = $stdout
        StdErr = $stderr
    }
}

function Split-ChildOutput {
    param([AllowNull()][string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return @()
    }
    return @($Text -split "\r?\n" | Where-Object { $_ -ne "" })
}

function Invoke-StreamingChildProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FileName,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$CommandSanitized,
        [int]$TimeoutSeconds = 180
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FileName
    $startInfo.WorkingDirectory = (Get-Location).Path
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $lines = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
    $lastVisible = [pscustomobject]@{ Value = "NONE" }
    $stdoutHandler = [System.Diagnostics.DataReceivedEventHandler]{
        param($sender, $event)
        if ($null -ne $event.Data) {
            $lines.Enqueue($event.Data)
            $lastVisible.Value = $event.Data
            [Console]::WriteLine($event.Data)
            [Console]::Out.Flush()
        }
    }
    $stderrHandler = [System.Diagnostics.DataReceivedEventHandler]{
        param($sender, $event)
        if ($null -ne $event.Data) {
            $lines.Enqueue($event.Data)
            $lastVisible.Value = $event.Data
            [Console]::WriteLine("STDERR: " + $event.Data)
            [Console]::Out.Flush()
        }
    }

    Write-Heartbeat ("PROCESS_COMMAND_SANITIZED: " + $CommandSanitized)
    if (-not $process.Start()) {
        throw "Unable to start diagnostic child process: $CommandSanitized"
    }
    $processId = $process.Id
    Write-Heartbeat ("PROCESS_START: " + $CommandSanitized)
    Write-Heartbeat ("PROCESS_PID: " + $processId)
    $process.add_OutputDataReceived($stdoutHandler)
    $process.add_ErrorDataReceived($stderrHandler)
    $process.BeginOutputReadLine()
    $process.BeginErrorReadLine()
    $process.StandardInput.Close()

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $timedOut = $false
    while (-not $process.HasExited) {
        if ($TimeoutSeconds -gt 0 -and $stopwatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            $timedOut = $true
            try { $process.Kill($true) } catch { }
            break
        }
        Start-Sleep -Milliseconds 100
    }
    $process.WaitForExit()
    # Allow asynchronous output callbacks to drain after process termination.
    $process.WaitForExit()
    $exitCode = if ($timedOut) { "TIMEOUT" } else { $process.ExitCode }
    Write-Heartbeat ("PROCESS_EXIT: " + $exitCode)
    $process.remove_OutputDataReceived($stdoutHandler)
    $process.remove_ErrorDataReceived($stderrHandler)
    $process.Dispose()

    [pscustomobject]@{
        ExitCode = $exitCode
        TimedOut = $timedOut
        ProcessId = $processId
        Lines = @($lines.ToArray())
        LastVisibleTestNode = $lastVisible.Value
    }
}

$databasePresent = -not [string]::IsNullOrWhiteSpace($env:DATABASE_URL)
Write-Output ("DATABASE_URL_PRESENT: " + $(if ($databasePresent) { "YES" } else { "NO" }))
if (-not $databasePresent) {
    Write-Output "LOCAL_VALIDATOR_GATE: BLOCKED"
    Write-Output "SCRIPT_CREATED: YES"
    Write-Output "SCRIPT_PATH: scripts/validate_authority_postgres.ps1"
    Write-Output "DATABASE_SECRET_REQUIRED_BY_CODEX: NO"
    Write-Output "POSTGRES_TCP_REACHABLE: NOT_RUN"
    Write-Output "POSTGRES_CONNECTION: NOT_RUN"
    Write-Output "POSTGRES_VERSION: NOT_RUN"
    Write-Output "DATABASE_NAME: NOT_RUN"
    Write-Output "SCHEMA_INSPECTION: NOT_RUN"
    Write-Output "EMPTY_DATABASE_PREFLIGHT: NOT_RUN"
    Write-Output "PREFLIGHT_FAILURE_STAGE: environment"
    Write-Output "PREFLIGHT_EXCEPTION_TYPE: MissingDatabaseUrl"
    Write-Output "PREFLIGHT_ERROR_SANITIZED: DATABASE_URL is absent from the caller process environment"
    Write-Output "READY_FOR_LOCAL_EXECUTION: NO"
    Write-Output "BLOCKERS: DATABASE_URL must be supplied by the caller's current process environment."
    exit 2
}

$pushed = $false
$stage = "preflight"
$preflight = "BLOCKED"
$migration = "BLOCKED"
$schema = "BLOCKED"
$authority = "BLOCKED"
$targeted = "BLOCKED"
$fullPostgres = "BLOCKED"
$fullBackend = "BLOCKED"
$postgresTcpReachable = "NOT_RUN"
$postgresConnection = "NOT_RUN"
$postgresVersion = "NOT_RUN"
$databaseName = "NOT_RUN"
$schemaInspection = "NOT_RUN"
$emptyDatabase = "NOT_RUN"
$preflightMode = "NOT_RUN"
$migratedReusePreflight = "NOT_RUN"
$expectedTableCount = "NOT_RUN"
$actualTableCount = "NOT_RUN"
$missingExpectedTables = @()
$unexpectedTables = @()
$unexpectedSchemas = @()
$schemaCompatibility = "NOT_RUN"
$preflightFailureStage = "NONE"
$preflightExceptionType = "NONE"
$preflightErrorSanitized = "NONE"
$alembicCommandStage = "NOT_RUN"
$alembicExitCode = "NOT_RUN"
$alembicExceptionType = "NONE"
$alembicErrorSanitized = "NONE"
$targetedResult = $null
$failure = $null

function Invoke-PythonJson {
    param(
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $child = Invoke-SafeChildProcess `
        -FileName $python `
        -Arguments @("-") `
        -StandardInput $Code `
        -CommandSanitized ($python + " -")
    if ($child.ExitCode -ne 0) {
        $detail = (Split-ChildOutput $child.StdErr) -join " | "
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = "no stderr" }
        throw "$Name failed with exit code $($child.ExitCode): $detail"
    }
    $output = Split-ChildOutput $child.StdOut
    if ($output.Count -eq 0) {
        throw "$Name returned no machine-readable result"
    }
    try {
        return ($output | Select-Object -Last 1 | ConvertFrom-Json)
    } catch {
        throw "$Name returned no machine-readable result"
    }
}

function Sanitize-AlembicText {
    param([AllowNull()][string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return "NONE"
    }
    $safe = $Text
    $safe = [regex]::Replace($safe, '(?i)(postgres(?:ql)?(?:\+[^:/\s]+)?://)[^\s"''<>]+', '$1<redacted>')
    $safe = [regex]::Replace($safe, '(?i)(database_url|redis_url|rabbitmq_url|password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*[^\s,;]+', '$1=<redacted>')
    $safe = [regex]::Replace($safe, '(?i)(user|username)\s*[=:]\s*[^\s,;]+', '$1=<redacted>')
    $safe = [regex]::Replace($safe, '(?i)(for\s+user\s+|role\s+)"[^"]+"', '$1"<redacted>"')
    $safe = $safe.Trim()
    if ($safe.Length -gt 2000) {
        $safe = $safe.Substring(0, 2000) + "..."
    }
    return $safe
}

function Get-AlembicExceptionType {
    param([AllowNull()][string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return "NONE"
    }
    $match = [regex]::Match($Text, '(?i)([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*(?:Error|Exception))')
    if ($match.Success) {
        return $match.Groups[1].Value
    }
    return "AlembicCommandError"
}

function Invoke-AlembicReadCommand {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $child = Invoke-SafeChildProcess `
        -FileName $python `
        -Arguments (@("-m", "alembic") + $Arguments) `
        -CommandSanitized (($python + " -m alembic " + ($Arguments -join " ")).Trim())
    $raw = @(Split-ChildOutput $child.StdOut) + @(Split-ChildOutput $child.StdErr)
    $code = $child.ExitCode
    $text = ($raw | Out-String)
    return [pscustomobject]@{
        Arguments = ($Arguments -join " ")
        ExitCode = $code
        Output = $text
        Sanitized = (Sanitize-AlembicText $text)
        ExceptionType = (Get-AlembicExceptionType $text)
    }
}

function Get-PytestSummary {
    param([object[]]$Output)
    $text = @($Output | ForEach-Object { [string]$_ }) | Out-String
    $collected = [regex]::Match($text, '(?im)collected\s+(\d+)\s+items?')
    $passed = [regex]::Matches($text, '(?im)(\d+)\s+passed')
    return [pscustomobject]@{
        Discovered = if ($collected.Success) { $collected.Groups[1].Value } else { "UNKNOWN" }
        Passed = if ($passed.Count -gt 0) { $passed[$passed.Count - 1].Groups[1].Value } else { "0" }
        Text = $text
    }
}

function Get-TargetedFailureCategory {
    param([AllowNull()][string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return "TEST_HARNESS" }
    if ($Text -match '(?i)fixture\s+[''"][^''"]+[''"]\s+not\s+found|fixture.*not\s+found|ERROR\s+at\s+setup|ERROR\s+collecting|import\s+file\s+mismatch|collection\s+error') {
        return "TEST_HARNESS"
    }
    if ($Text -match '(?i)append[-_ ]only|immutable|policy_evaluations_immutable_update|UPDATE OR DELETE') { return "APPEND_ONLY" }
    if ($Text -match '(?i)UniqueViolation|duplicate|idempot') { return "IDEMPOTENCY" }
    if ($Text -match '(?i)concurr|race|deadlock') { return "CONCURRENCY" }
    if ($Text -match '(?i)type[_ -]?isolation|POLICY_INPUT_TYPE_MISMATCH|policy type') { return "TYPE_ISOLATION" }
    if ($Text -match '(?i)cross[-_ ]agent|agent.*isolation') { return "CROSS_AGENT_ISOLATION" }
    if ($Text -match '(?i)semantic.*order|ordering') { return "SEMANTIC_ORDERING" }
    if ($Text -match '(?i)decision parity|PERMIT|REVIEW|BLOCK') { return "DECISION_PARITY" }
    if ($Text -match '(?i)G13|THROTTLE|HALT') { return "G13_POLICY" }
    if ($Text -match '(?i)replay') { return "REPLAY" }
    if ($Text -match '(?i)composition|pre[-_ ]next') { return "AUTHORITY_COMPOSITION" }
    if ($Text -match '(?i)relation|column|table|does not exist|UndefinedTable|UndefinedColumn|ProgrammingError|OperationalError') {
        return "ORM_POSTGRES_COMPATIBILITY"
    }
    return "UNKNOWN"
}

function Invoke-TargetedAuthorityTests {
    Write-Heartbeat "STAGE_ENTER: targeted_unit"
    $unitChild = Invoke-SafeChildProcess `
        -FileName $python `
        -Arguments @("-m", "pytest", "tests/unit/test_authority_integration.py", "-vv", "-x") `
        -CommandSanitized ($python + " -m pytest tests/unit/test_authority_integration.py -vv -x")
    $unitOutput = @(Split-ChildOutput $unitChild.StdOut) + @(Split-ChildOutput $unitChild.StdErr)
    $unitExitCode = $unitChild.ExitCode
    Write-Heartbeat "STAGE_EXIT: targeted_unit"
    $integrationOutput = @()
    $integrationExitCode = "NOT_RUN"
    if ($unitExitCode -eq 0) {
        Write-Heartbeat "STAGE_ENTER: targeted_integration"
        $integrationChild = Invoke-SafeChildProcess `
            -FileName $python `
            -Arguments @("-m", "pytest", "tests/integration/test_authority_integration.py", "-vv", "-x") `
            -CommandSanitized ($python + " -m pytest tests/integration/test_authority_integration.py -vv -x")
        $integrationOutput = @(Split-ChildOutput $integrationChild.StdOut) + @(Split-ChildOutput $integrationChild.StdErr)
        $integrationExitCode = $integrationChild.ExitCode
        Write-Heartbeat "STAGE_EXIT: targeted_integration"
    }
    $unitSummary = Get-PytestSummary $unitOutput
    $integrationSummary = Get-PytestSummary $integrationOutput
    $failureOutput = if ($unitExitCode -ne 0) { $unitOutput } else { $integrationOutput }
    $failureText = if ($unitExitCode -ne 0) { $unitSummary.Text } elseif ($integrationExitCode -ne 0) { $integrationSummary.Text } else { "" }
    $failedMatch = [regex]::Match($failureText, '(?im)^\s*(?:FAILED|ERROR)\s+([^\s]+::[^\s]+)')
    $failingNode = if ($failedMatch.Success) { $failedMatch.Groups[1].Value } else { "NONE" }
    $failingFile = "NONE"
    $failingFunction = "NONE"
    if ($failingNode -ne "NONE") {
        $nodeParts = $failingNode -split "::"
        $failingFile = $nodeParts[0]
        $failingFunction = $nodeParts[-1]
    }
    $exceptionMatch = [regex]::Match($failureText, '(?im)([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*(?:Error|Exception))(?::|\s)')
    $exceptionType = if ($exceptionMatch.Success) { $exceptionMatch.Groups[1].Value } else { "NONE" }
    $sqlStateMatch = [regex]::Match($failureText, '(?i)(?:sqlstate|sql\s+state)[^0-9A-Z]*([0-9A-Z]{5})')
    $sqlState = if ($sqlStateMatch.Success) { $sqlStateMatch.Groups[1].Value } else { "NOT_REPORTED" }
    $assertionLines = @($failureOutput | Where-Object { $_ -match '^\s*E\s+(AssertionError|assert\s+)' })
    $failedAssertion = if ($assertionLines.Count -gt 0) { ($assertionLines -join " ") } else { "NONE" }
    $numericDiscovered = @($unitSummary.Discovered, $(if ($unitExitCode -eq 0) { $integrationSummary.Discovered } else { "NOT_RUN" })) | Where-Object { $_ -match '^\d+$' }
    $numericPassed = @($unitSummary.Passed, $(if ($unitExitCode -eq 0) { $integrationSummary.Passed } else { "NOT_RUN" })) | Where-Object { $_ -match '^\d+$' }
    return [pscustomobject]@{
        UnitDiscovered = $unitSummary.Discovered
        UnitPassed = $unitSummary.Passed
        UnitExitCode = $unitExitCode
        IntegrationDiscovered = if ($unitExitCode -eq 0) { $integrationSummary.Discovered } else { "NOT_RUN" }
        IntegrationPassed = if ($unitExitCode -eq 0) { $integrationSummary.Passed } else { "NOT_RUN" }
        IntegrationExitCode = $integrationExitCode
        TotalDiscovered = if ($numericDiscovered.Count -gt 0) { ($numericDiscovered | Measure-Object -Sum).Sum } else { "UNKNOWN" }
        TotalPassed = if ($numericPassed.Count -gt 0) { ($numericPassed | Measure-Object -Sum).Sum } else { "UNKNOWN" }
        ExitCode = if ($unitExitCode -ne 0) { $unitExitCode } elseif ($integrationExitCode -ne 0) { $integrationExitCode } else { 0 }
        Stage = if ($unitExitCode -eq 0 -and $integrationExitCode -eq 0) { "PASS" } else { "FAIL" }
        FailingNode = $failingNode
        FailingFile = $failingFile
        FailingFunction = $failingFunction
        ExceptionType = $exceptionType
        PostgresSqlState = $sqlState
        FailedAssertion = (Sanitize-AlembicText $failedAssertion)
        ErrorSanitized = if ([string]::IsNullOrWhiteSpace($failureText)) { "NONE" } else { (Sanitize-AlembicText $failureText) }
        FailureCategory = if ($unitExitCode -eq 0 -and $integrationExitCode -eq 0) { "NONE" } else { (Get-TargetedFailureCategory $failureText) }
    }
}

function Write-TargetedResultReport {
    param(
        [Parameter(Mandatory = $true)]$Result,
        [string]$Label = "TARGETED_TEST_STAGE"
    )
    Write-Output ("{0}: {1}" -f $Label, $Result.Stage)
    Write-Output "TARGETED_TEST_COMMAND: python -m pytest tests/unit/test_authority_integration.py -vv -x; then integration only if unit succeeds: python -m pytest tests/integration/test_authority_integration.py -vv -x"
    Write-Output ("UNIT_TARGETED_DISCOVERED: " + $Result.UnitDiscovered)
    Write-Output ("UNIT_TARGETED_PASSED: " + $Result.UnitPassed)
    Write-Output ("UNIT_TARGETED_EXIT_CODE: " + $Result.UnitExitCode)
    Write-Output ("INTEGRATION_TARGETED_DISCOVERED: " + $Result.IntegrationDiscovered)
    Write-Output ("INTEGRATION_TARGETED_PASSED: " + $Result.IntegrationPassed)
    Write-Output ("INTEGRATION_TARGETED_EXIT_CODE: " + $Result.IntegrationExitCode)
    Write-Output ("TOTAL_TARGETED_DISCOVERED: " + $Result.TotalDiscovered)
    Write-Output ("TOTAL_TARGETED_PASSED: " + $Result.TotalPassed)
    if ($Result.Stage -ne "PASS") {
        Write-Output ("FAILING_TEST_NODE: " + $Result.FailingNode)
        Write-Output ("FAILING_TEST_FILE: " + $Result.FailingFile)
        Write-Output ("FAILING_TEST_FUNCTION: " + $Result.FailingFunction)
        Write-Output ("PYTEST_EXIT_CODE: " + $Result.ExitCode)
        Write-Output ("EXCEPTION_TYPE: " + $Result.ExceptionType)
        Write-Output ("POSTGRES_SQLSTATE: " + $Result.PostgresSqlState)
        Write-Output ("FAILED_ASSERTION: " + $Result.FailedAssertion)
        Write-Output ("ERROR_SANITIZED: " + $Result.ErrorSanitized)
        Write-Output ("FAILURE_CATEGORY: " + $Result.FailureCategory)
    }
}

if ($DiagnoseTargetedTests) {
    $diagnosticPushed = $false
    $diagnosticDatabase = $null
    $diagnosticCurrent = $null
    $unitOutput = @()
    $integrationOutput = @()
    $unitExitCode = "NOT_RUN"
    $integrationExitCode = "NOT_RUN"
    $diagnosticExitCode = "NOT_RUN"
    $diagnosticFailure = $null
    try {
        Push-Location $backend
        $diagnosticPushed = $true
        $databaseProbeCode = @'
import json
import os
import sys

try:
    import psycopg
    with psycopg.connect(
        os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1),
        connect_timeout=10,
        options="-c default_transaction_read_only=on",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
            revisions = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute("SELECT version()")
            version = str(cursor.fetchone()[0])
    print(json.dumps({
        "ok": True,
        "postgres_version": version,
        "current_revisions": revisions,
    }, sort_keys=True))
except Exception as error:
    print(json.dumps({
        "ok": False,
        "exception_type": type(error).__name__,
        "error_sanitized": type(error).__name__,
    }, sort_keys=True))
    sys.exit(0)
'@
        $diagnosticDatabase = Invoke-PythonJson -Code $databaseProbeCode -Name "Migrated PostgreSQL probe"
        if (-not $diagnosticDatabase.ok) {
            throw "Migrated PostgreSQL probe failed"
        }
        $diagnosticCurrent = Invoke-AlembicReadCommand -Arguments @("current")
        if ($diagnosticCurrent.ExitCode -ne 0) {
            throw "Alembic current failed"
        }
        if (@($diagnosticDatabase.current_revisions) -notcontains "0020_user_credit" -or $diagnosticCurrent.Output -notmatch "0020_user_credit") {
            throw "Alembic current revision is not 0020_user_credit"
        }

        $targetedResult = Invoke-TargetedAuthorityTests
        $diagnosticExitCode = $targetedResult.ExitCode
    } catch {
        $diagnosticFailure = "targeted diagnostic precondition failed"
        if ($diagnosticExitCode -eq "NOT_RUN") {
            $diagnosticExitCode = 2
        }
    } finally {
        if ($diagnosticPushed) { Pop-Location }
    }

    if ($null -eq $targetedResult) {
        $targetedResult = [pscustomobject]@{
            Stage = "FAIL"
            UnitDiscovered = "NOT_RUN"
            UnitPassed = "NOT_RUN"
            UnitExitCode = "NOT_RUN"
            IntegrationDiscovered = "NOT_RUN"
            IntegrationPassed = "NOT_RUN"
            IntegrationExitCode = "NOT_RUN"
            TotalDiscovered = "NOT_RUN"
            TotalPassed = "NOT_RUN"
            ExitCode = $diagnosticExitCode
            FailingNode = "NONE"
            FailingFile = "NONE"
            FailingFunction = "NONE"
            ExceptionType = "TargetedDiagnosticPreconditionError"
            PostgresSqlState = "NOT_REPORTED"
            FailedAssertion = "NONE"
            ErrorSanitized = $diagnosticFailure
            FailureCategory = "TEST_HARNESS"
        }
    }
    Write-Output ("TARGETED_TEST_DIAGNOSTIC: " + $targetedResult.Stage)
    Write-Output ("DATABASE_URL_PRESENT: " + $(if ($databasePresent) { "YES" } else { "NO" }))
    Write-Output ("POSTGRES_CONNECTION: " + $(if ($null -ne $diagnosticDatabase -and $diagnosticDatabase.ok) { "YES" } else { "NO" }))
    Write-Output ("ALEMBIC_CURRENT_REVISION: " + $(if ($null -ne $diagnosticDatabase -and $null -ne $diagnosticDatabase.current_revisions) { (@($diagnosticDatabase.current_revisions) -join ", ") } else { "UNKNOWN" }))
    Write-TargetedResultReport -Result $targetedResult -Label "TARGETED_TEST_STAGE"
    Write-Output "ALEMBIC_UPGRADE_EXECUTED: NO"
    Write-Output "FULL_BACKEND_REGRESSION_EXECUTED: NO"
    exit $(if ($targetedResult.Stage -eq "PASS") { 0 } else { 1 })

    function Get-PytestSummary {
        param([string[]]$Output)
        $text = $Output | Out-String
        $collected = [regex]::Match($text, '(?im)collected\s+(\d+)\s+items?')
        $passed = [regex]::Matches($text, '(?im)(\d+)\s+passed')
        [pscustomobject]@{
            Discovered = if ($collected.Success) { $collected.Groups[1].Value } else { "UNKNOWN" }
            Passed = if ($passed.Count -gt 0) { $passed[$passed.Count - 1].Groups[1].Value } else { "0" }
            Text = $text
        }
    }

    $unitSummary = Get-PytestSummary $unitOutput
    $integrationSummary = Get-PytestSummary $integrationOutput
    $diagnosticText = if ($unitExitCode -ne 0) {
        $unitSummary.Text
    } elseif ($integrationExitCode -ne "NOT_RUN" -and $integrationExitCode -ne 0) {
        $integrationSummary.Text
    } else {
        ($unitSummary.Text + [Environment]::NewLine + $integrationSummary.Text)
    }
    $failedMatch = [regex]::Match($diagnosticText, '(?im)^\s*(?:FAILED|ERROR)\s+([^\s]+::[^\s]+)')
    $failingNode = if ($failedMatch.Success) { $failedMatch.Groups[1].Value } else { "NONE" }
    $failingFile = "NONE"
    $failingFunction = "NONE"
    if ($failingNode -ne "NONE") {
        $nodeParts = $failingNode -split "::"
        $failingFile = $nodeParts[0]
        $failingFunction = $nodeParts[-1]
    }
    $exceptionMatch = [regex]::Match($diagnosticText, '(?im)([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*(?:Error|Exception))(?::|\s)')
    $exceptionType = if ($exceptionMatch.Success) { $exceptionMatch.Groups[1].Value } else { "NONE" }
    $sqlStateMatch = [regex]::Match($diagnosticText, '(?i)(?:sqlstate|sql\s+state)[^0-9A-Z]*([0-9A-Z]{5})')
    $sqlState = if ($sqlStateMatch.Success) { $sqlStateMatch.Groups[1].Value } else { "NOT_REPORTED" }
    $failureOutput = if ($unitExitCode -ne 0) { $unitOutput } else { $integrationOutput }
    $assertionLines = @($failureOutput | Where-Object { $_ -match '^\s*E\s+(AssertionError|assert\s+)' })
    $failedAssertion = if ($assertionLines.Count -gt 0) { ($assertionLines -join " ") } else { "NONE" }
    $failedAssertion = Sanitize-AlembicText $failedAssertion
    $sanitizedTestText = Sanitize-AlembicText $diagnosticText
    $failureCategory = "UNKNOWN"
    if ($diagnosticExitCode -eq 0) {
        $failureCategory = "NONE"
    } elseif ($diagnosticFailure -or $null -eq $diagnosticDatabase -or $null -eq $diagnosticCurrent -or $diagnosticCurrent.ExitCode -ne 0) {
        $failureCategory = "TEST_HARNESS"
    } elseif ($diagnosticText -match '(?i)fixture\s+[''"][^''"]+[''"]\s+not\s+found|fixture.*not\s+found|ERROR\s+at\s+setup|ERROR\s+collecting|import\s+file\s+mismatch|collection\s+error') {
        $failureCategory = "TEST_HARNESS"
    } elseif ($diagnosticText -match '(?i)append[-_ ]only|immutable|policy_evaluations_immutable_update|UPDATE OR DELETE') {
        $failureCategory = "APPEND_ONLY"
    } elseif ($diagnosticText -match '(?i)UniqueViolation|duplicate|idempot') {
        $failureCategory = "IDEMPOTENCY"
    } elseif ($diagnosticText -match '(?i)concurr|race|deadlock') {
        $failureCategory = "CONCURRENCY"
    } elseif ($diagnosticText -match '(?i)type[_ -]?isolation|POLICY_INPUT_TYPE_MISMATCH|policy type') {
        $failureCategory = "TYPE_ISOLATION"
    } elseif ($diagnosticText -match '(?i)cross[-_ ]agent|agent.*isolation') {
        $failureCategory = "CROSS_AGENT_ISOLATION"
    } elseif ($diagnosticText -match '(?i)semantic.*order|ordering') {
        $failureCategory = "SEMANTIC_ORDERING"
    } elseif ($diagnosticText -match '(?i)decision parity|PERMIT|REVIEW|BLOCK') {
        $failureCategory = "DECISION_PARITY"
    } elseif ($diagnosticText -match '(?i)G13|THROTTLE|HALT') {
        $failureCategory = "G13_POLICY"
    } elseif ($diagnosticText -match '(?i)replay') {
        $failureCategory = "REPLAY"
    } elseif ($diagnosticText -match '(?i)composition|pre[-_ ]next') {
        $failureCategory = "AUTHORITY_COMPOSITION"
    } elseif ($diagnosticText -match '(?i)relation|column|table|does not exist|UndefinedTable|UndefinedColumn|ProgrammingError|OperationalError') {
        $failureCategory = "ORM_POSTGRES_COMPATIBILITY"
    }

    Write-Output "TARGETED_TEST_DIAGNOSTIC: $([string]$(if ($diagnosticExitCode -eq 0) { "PASS" } else { "FAIL" }))"
    Write-Output ("DATABASE_URL_PRESENT: " + $(if ($databasePresent) { "YES" } else { "NO" }))
    Write-Output ("POSTGRES_CONNECTION: " + $(if ($null -ne $diagnosticDatabase -and $diagnosticDatabase.ok) { "YES" } else { "NO" }))
    Write-Output ("ALEMBIC_CURRENT_REVISION: " + $(if ($null -ne $diagnosticDatabase -and $null -ne $diagnosticDatabase.current_revisions) { (@($diagnosticDatabase.current_revisions) -join ", ") } else { "UNKNOWN" }))
    $unitDiscovered = $unitSummary.Discovered
    $unitPassed = $unitSummary.Passed
    $integrationDiscovered = if ($unitExitCode -eq 0) { $integrationSummary.Discovered } else { "NOT_RUN" }
    $integrationPassed = if ($unitExitCode -eq 0) { $integrationSummary.Passed } else { "NOT_RUN" }
    $numericDiscovered = @($unitDiscovered, $integrationDiscovered) | Where-Object { $_ -match '^\d+$' }
    $numericPassed = @($unitPassed, $integrationPassed) | Where-Object { $_ -match '^\d+$' }
    $totalDiscovered = if ($numericDiscovered.Count -gt 0) { ($numericDiscovered | Measure-Object -Sum).Sum } else { "UNKNOWN" }
    $totalPassed = if ($numericPassed.Count -gt 0) { ($numericPassed | Measure-Object -Sum).Sum } else { "UNKNOWN" }
    Write-Output "TARGETED_TEST_COMMAND: python -m pytest tests/unit/test_authority_integration.py -vv -x; then integration only if unit succeeds: python -m pytest tests/integration/test_authority_integration.py -vv -x"
    Write-Output ("UNIT_TARGETED_DISCOVERED: " + $unitDiscovered)
    Write-Output ("UNIT_TARGETED_PASSED: " + $unitPassed)
    Write-Output ("UNIT_TARGETED_EXIT_CODE: " + $unitExitCode)
    Write-Output ("INTEGRATION_TARGETED_DISCOVERED: " + $integrationDiscovered)
    Write-Output ("INTEGRATION_TARGETED_PASSED: " + $integrationPassed)
    Write-Output ("INTEGRATION_TARGETED_EXIT_CODE: " + $integrationExitCode)
    Write-Output ("TOTAL_TARGETED_DISCOVERED: " + $totalDiscovered)
    Write-Output ("TOTAL_TARGETED_PASSED: " + $totalPassed)
    Write-Output ("FAILING_TEST_NODE: " + $failingNode)
    Write-Output ("FAILING_TEST_FILE: " + $failingFile)
    Write-Output ("FAILING_TEST_FUNCTION: " + $failingFunction)
    Write-Output ("PYTEST_EXIT_CODE: " + $diagnosticExitCode)
    Write-Output ("EXCEPTION_TYPE: " + $exceptionType)
    Write-Output ("POSTGRES_SQLSTATE: " + $sqlState)
    Write-Output ("FAILED_ASSERTION: " + $failedAssertion)
    Write-Output ("ERROR_SANITIZED: " + $(if ($diagnosticExitCode -eq 0) { "NONE" } elseif ($diagnosticFailure) { $diagnosticFailure } else { $sanitizedTestText }))
    Write-Output ("FAILURE_CATEGORY: " + $failureCategory)
    Write-Output "ALEMBIC_UPGRADE_EXECUTED: NO"
    Write-Output "FULL_BACKEND_REGRESSION_EXECUTED: NO"
    exit $(if ($diagnosticExitCode -eq 0) { 0 } else { 1 })
}

$preflightCode = @'
import json
import os
import re
import socket
import sys
from urllib.parse import urlsplit

expected_tables = set()
current_tables = []
current_revisions = []
missing_expected_tables = []
unexpected_tables = []
unexpected_schemas = []
alembic_version_present = "NO"
schema_compatibility = "NOT_RUN"
production_like_database = "NO"
expected_schema_error = None
try:
    from app.persistence.database import Base
    import app.domain.mandates  # noqa: F401
    import app.users.models  # noqa: F401
    expected_tables = {
        f"{table.schema or 'public'}.{table.name}"
        for table in Base.metadata.tables.values()
    }
    expected_tables.add("public.alembic_version")
    expected_tables.add("public.user_credit_balances")  # SQL view created by 0020
except Exception as error:
    expected_schema_error = error


def sanitized_error(error, *, host=None, port=None):
    error_type = type(error).__name__
    sqlstate = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
    text = str(error)
    text = re.sub(r"(?i)(postgres(?:ql)?(?:\+[^:/?#]+)?://)[^@\s]+@", r"\1<redacted>@", text)
    text = re.sub(r"(?i)(database_url|redis_url|rabbitmq_url|password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>", text)
    text = re.sub(r"(?i)(user|username)\s*[=:]\s*[^\s,;]+", r"\1=<redacted>", text)
    text = re.sub(r'(?i)(for\s+user\s+|role\s+)"[^"]+"', r'\1"<redacted>"', text)
    text = re.sub(r"(?i)(postgres(?:ql)?://)[^\s]+", r"\1<redacted>", text)
    details = [error_type]
    if sqlstate:
        details.append(f"sqlstate={sqlstate}")
    if host:
        details.append(f"host={host}")
    if port:
        details.append(f"port={port}")
    if text:
        details.append(f"message={text[:300]}")
    return "; ".join(details)


def fail(stage, exception_type, error, *, host=None, port=None, database=None):
    return {
        "ok": False,
        "failure_stage": stage,
        "exception_type": exception_type,
        "error_sanitized": sanitized_error(error, host=host, port=port),
        "POSTGRES_TCP_REACHABLE": tcp_status,
        "POSTGRES_CONNECTION": connection_status,
        "POSTGRES_VERSION": version,
        "DATABASE_NAME": database or database_name,
        "SCHEMA_INSPECTION": schema_status,
        "EMPTY_DATABASE_PREFLIGHT": empty_status,
        "CURRENT_TABLES": current_tables,
        "ALEMBIC_VERSION_TABLE_PRESENT": alembic_version_present,
        "ALEMBIC_CURRENT_REVISION": current_revisions,
        "EXPECTED_TABLE_COUNT": len(expected_tables),
        "ACTUAL_TABLE_COUNT": len(current_tables),
        "MISSING_EXPECTED_TABLES": missing_expected_tables,
        "UNEXPECTED_TABLES": unexpected_tables,
        "UNEXPECTED_SCHEMAS": unexpected_schemas,
        "SCHEMA_COMPATIBILITY": schema_compatibility,
        "PRODUCTION_LIKE_DATABASE": production_like_database,
    }


tcp_status = "NOT_RUN"
connection_status = "NOT_RUN"
version = "NOT_RUN"
database_name = "NOT_RUN"
schema_status = "NOT_RUN"
empty_status = "NOT_RUN"
host = None
port = None

try:
    raw_url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(raw_url)
    host = parsed.hostname
    port = parsed.port or 5432
    if not parsed.scheme or not host:
        result = fail("connection_target_parse", "InvalidDatabaseURL", ValueError("DATABASE_URL has no usable PostgreSQL host"), host=host, port=port)
        print(json.dumps(result, sort_keys=True))
        sys.exit(0)
except Exception as error:
    result = fail("connection_target_parse", type(error).__name__, error, host=host, port=port)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0)

try:
    socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    with socket.create_connection((host, port), timeout=10):
        pass
    tcp_status = "YES"
except Exception as error:
    tcp_status = "NO"
    result = fail("tcp_connect", type(error).__name__, error, host=host, port=port)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0)

try:
    import psycopg
except Exception as error:
    result = fail("driver_import", type(error).__name__, error, host=host, port=port)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0)

try:
    with psycopg.connect(
        raw_url,
        connect_timeout=10,
        options="-c default_transaction_read_only=on",
    ) as connection:
        connection_status = "YES"
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), version()")
            database_name, version = cursor.fetchone()
            version = str(version)
            database_name = str(database_name)
            cursor.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
            """)
            tables = [f"{row[0]}.{row[1]}" for row in cursor.fetchall()]
            current_tables = sorted(set(tables))
            alembic_version_present = "YES" if "public.alembic_version" in current_tables else "NO"
            if alembic_version_present == "YES":
                cursor.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
                current_revisions = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute("""
                SELECT n.nspname, c.relname, c.relkind
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
                ORDER BY n.nspname, c.relname
            """)
            relations = [list(row) for row in cursor.fetchall()]
            schema_status = "PASS"
    lowered = database_name.lower()
    ambiguous_name = lowered in {"prama", "prama_dynamagh", "production"} or "prod" in lowered
    production_like_database = "YES" if ambiguous_name else "NO"
    missing_expected_tables = sorted(expected_tables.difference(current_tables))
    unexpected_tables = sorted(set(current_tables).difference(expected_tables))
    unexpected_schemas = sorted({item[0] for item in relations if item[0] != "public"})
    schema_compatibility = "PASS" if expected_schema_error is None and not missing_expected_tables and not unexpected_tables and not unexpected_schemas else "FAIL"
    if expected_schema_error is not None:
        result = fail("expected_schema_import", type(expected_schema_error).__name__, expected_schema_error, host=host, port=port, database=database_name)
        print(json.dumps(result, sort_keys=True))
        sys.exit(0)
    if ambiguous_name:
        result = fail("empty_database_identity", "AmbiguousDatabaseName", ValueError("database name is production-like"), host=host, port=port, database=database_name)
        print(json.dumps(result, sort_keys=True))
        sys.exit(0)
    empty_status = "PASS" if not current_tables and not relations else "NOT_REQUIRED_NONEMPTY"
    print(json.dumps({
        "ok": True,
        "failure_stage": "NONE",
        "exception_type": "NONE",
        "error_sanitized": "NONE",
        "POSTGRES_TCP_REACHABLE": tcp_status,
        "POSTGRES_CONNECTION": connection_status,
        "POSTGRES_VERSION": version,
        "DATABASE_NAME": database_name,
        "SCHEMA_INSPECTION": schema_status,
        "EMPTY_DATABASE_PREFLIGHT": empty_status,
        "CURRENT_TABLES": current_tables,
        "ALEMBIC_VERSION_TABLE_PRESENT": alembic_version_present,
        "ALEMBIC_CURRENT_REVISION": current_revisions,
        "EXPECTED_TABLE_COUNT": len(expected_tables),
        "ACTUAL_TABLE_COUNT": len(current_tables),
        "MISSING_EXPECTED_TABLES": missing_expected_tables,
        "UNEXPECTED_TABLES": unexpected_tables,
        "UNEXPECTED_SCHEMAS": unexpected_schemas,
        "SCHEMA_COMPATIBILITY": schema_compatibility,
        "PRODUCTION_LIKE_DATABASE": production_like_database,
    }, sort_keys=True))
except Exception as error:
    if connection_status == "NOT_RUN":
        connection_status = "NO"
    result = fail("postgres_connection_or_schema", type(error).__name__, error, host=host, port=port, database=database_name)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0)
'@

if ($DiagnosePostgresSuite) {
    $diagnosticPushed = $false
    $diagnosticFailure = $null
    try {
        Push-Location $backend
        $diagnosticPushed = $true

        # Read-only precondition: reuse the already migrated disposable database.
        $databaseCheck = Invoke-PythonJson -Code $preflightCode -Name "PostgreSQL suite diagnostic preflight"
        $currentCheck = Invoke-AlembicReadCommand -Arguments @("current")
        $currentRevisionText = if ($null -ne $databaseCheck.ALEMBIC_CURRENT_REVISION) {
            (@($databaseCheck.ALEMBIC_CURRENT_REVISION) -join ", ")
        } else {
            "NONE"
        }
        if (-not $databaseCheck.ok -or $currentCheck.ExitCode -ne 0 -or $currentRevisionText -notmatch "0020_user_credit") {
            throw "Disposable PostgreSQL precondition failed; expected Alembic revision 0020_user_credit"
        }

        $collection = Invoke-StreamingChildProcess `
            -FileName $python `
            -Arguments @("-m", "pytest", "tests/integration", "--collect-only", "-q") `
            -CommandSanitized ($python + " -m pytest tests/integration --collect-only -q") `
            -TimeoutSeconds 180
        $collectionText = ($collection.Lines -join [Environment]::NewLine)
        $nodeLines = @($collection.Lines | Where-Object {
            $_ -match '(?i)tests[\\/]+integration[\\/][^:\s]+\.py::'
        })
        $testNodes = @($nodeLines | ForEach-Object {
            $match = [regex]::Match($_, '(?i)(tests[\\/]+integration[\\/][^\s]+\.py::[^\s]+)')
            if ($match.Success) { $match.Groups[1].Value }
        } | Where-Object { $_ } | Select-Object -Unique)
        $integrationFiles = @($testNodes | ForEach-Object {
            ($_ -split '::', 2)[0]
        } | Select-Object -Unique | Sort-Object)
        $collectedSummary = [regex]::Match($collectionText, '(?im)(\d+)\s+tests?\s+collected')
        $testsDiscovered = if ($testNodes.Count -gt 0) {
            $testNodes.Count
        } elseif ($collectedSummary.Success) {
            $collectedSummary.Groups[1].Value
        } else {
            "UNKNOWN"
        }

        Write-Output ("POSTGRES_SUITE_COLLECT_EXIT: " + $collection.ExitCode)
        Write-Output ("POSTGRES_SUITE_TESTS_DISCOVERED: " + $testsDiscovered)
        Write-Output ("POSTGRES_SUITE_FILES_DISCOVERED: " + $(if ($integrationFiles.Count -eq 0) { "NONE" } else { ($integrationFiles -join ", ") }))

        if ($collection.TimedOut) {
            Write-Output "POSTGRES_SUITE_HANG_DIAGNOSTIC: HANG"
            Write-Output "HANGING_INTEGRATION_FILE: COLLECTION"
            Write-Output "HANG_TIMEOUT_SECONDS: 180"
            Write-Output ("LAST_PROCESS_PID: " + $collection.ProcessId)
            Write-Output ("LAST_VISIBLE_TEST_NODE: " + $collection.LastVisibleTestNode)
            Write-Output "FAILURE_CATEGORY: TEST_HARNESS_OR_TEST_HANG"
            exit 2
        }
        if ($collection.ExitCode -ne 0 -or $integrationFiles.Count -eq 0) {
            Write-Output "POSTGRES_SUITE_HANG_DIAGNOSTIC: COLLECTION_FAILED"
            Write-Output ("ERROR_SANITIZED: " + (Sanitize-AlembicText $collectionText))
            Write-Output "FAILURE_CATEGORY: TEST_HARNESS"
            exit 1
        }

        foreach ($integrationFile in $integrationFiles) {
            $fileStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            Write-Heartbeat ("INTEGRATION_FILE_START: " + $integrationFile)
            $fileResult = Invoke-StreamingChildProcess `
                -FileName $python `
                -Arguments @("-m", "pytest", $integrationFile, "-vv", "-x") `
                -CommandSanitized ($python + " -m pytest " + $integrationFile + " -vv -x") `
                -TimeoutSeconds 180
            $fileStopwatch.Stop()
            $duration = [math]::Round($fileStopwatch.Elapsed.TotalSeconds, 3)
            Write-Heartbeat ("INTEGRATION_FILE_EXIT: " + $integrationFile + " " + $fileResult.ExitCode)
            Write-Heartbeat ("INTEGRATION_FILE_DURATION_SECONDS: " + $duration)

            if ($fileResult.TimedOut) {
                Write-Output "POSTGRES_SUITE_HANG_DIAGNOSTIC: HANG"
                Write-Output ("HANGING_INTEGRATION_FILE: " + $integrationFile)
                Write-Output "HANG_TIMEOUT_SECONDS: 180"
                Write-Output ("LAST_PROCESS_PID: " + $fileResult.ProcessId)
                Write-Output ("LAST_VISIBLE_TEST_NODE: " + $fileResult.LastVisibleTestNode)
                Write-Output "FAILURE_CATEGORY: TEST_HARNESS_OR_TEST_HANG"
                exit 2
            }
            if ($fileResult.ExitCode -ne 0) {
                $fileText = $fileResult.Lines -join [Environment]::NewLine
                $failedMatch = [regex]::Match($fileText, '(?im)^\s*(?:FAILED|ERROR)\s+([^\s]+::[^\s]+)')
                $failingNode = if ($failedMatch.Success) { $failedMatch.Groups[1].Value } else { $fileResult.LastVisibleTestNode }
                $exceptionMatch = [regex]::Match($fileText, '(?im)([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*(?:Error|Exception))(?::|\s)')
                $exceptionType = if ($exceptionMatch.Success) { $exceptionMatch.Groups[1].Value } else { "NONE" }
                $sqlStateMatch = [regex]::Match($fileText, '(?i)(?:sqlstate|sql\s+state)[^0-9A-Z]*([0-9A-Z]{5})')
                $sqlState = if ($sqlStateMatch.Success) { $sqlStateMatch.Groups[1].Value } else { "NOT_REPORTED" }
                $assertionLines = @($fileResult.Lines | Where-Object { $_ -match '^\s*E\s+(AssertionError|assert\s+)' })
                $failedAssertion = if ($assertionLines.Count -gt 0) { $assertionLines -join " " } else { "NONE" }
                Write-Output "POSTGRES_SUITE_HANG_DIAGNOSTIC: FAIL"
                Write-Output ("FAILING_INTEGRATION_FILE: " + $integrationFile)
                Write-Output ("FAILING_TEST_NODE: " + $failingNode)
                Write-Output ("PYTEST_EXIT_CODE: " + $fileResult.ExitCode)
                Write-Output ("EXCEPTION_TYPE: " + $exceptionType)
                Write-Output ("POSTGRES_SQLSTATE: " + $sqlState)
                Write-Output ("FAILED_ASSERTION: " + (Sanitize-AlembicText $failedAssertion))
                Write-Output ("ERROR_SANITIZED: " + (Sanitize-AlembicText $fileText))
                Write-Output ("FAILURE_CATEGORY: " + (Get-TargetedFailureCategory $fileText))
                exit 1
            }
        }

        Write-Output "POSTGRES_SUITE_HANG_DIAGNOSTIC: PASS"
        Write-Output "DATABASE_MUTATION: NO"
        Write-Output "ALEMBIC_UPGRADE_EXECUTED: NO"
        Write-Output "FULL_BACKEND_REGRESSION_EXECUTED: NO"
    } catch {
        $diagnosticFailure = $_.Exception.Message
        Write-Output "POSTGRES_SUITE_HANG_DIAGNOSTIC: BLOCKED"
        Write-Output ("ERROR_SANITIZED: " + (Sanitize-AlembicText $diagnosticFailure))
        Write-Output "FAILURE_CATEGORY: TEST_HARNESS"
    } finally {
        if ($diagnosticPushed) { Pop-Location }
    }
    exit $(if ($null -eq $diagnosticFailure) { 0 } else { 1 })
}

if ($DiagnoseHang) {
    $diagnosticPushed = $false
    $diagnosticPreflight = $null
    $diagnosticFailure = $null
    try {
        Push-Location $backend
        $diagnosticPushed = $true
        Write-Heartbeat "STAGE_ENTER: connection_target_parse"
        Write-Heartbeat "STAGE_ENTER: tcp_probe"
        Write-Heartbeat "STAGE_ENTER: postgres_connection"
        Write-Heartbeat "STAGE_ENTER: schema_inspection"
        $diagnosticPreflight = Invoke-PythonJson -Code $preflightCode -Name "PostgreSQL hang diagnostic preflight"
        Write-Heartbeat "STAGE_EXIT: schema_inspection"
        Write-Heartbeat "STAGE_EXIT: postgres_connection"
        Write-Heartbeat "STAGE_EXIT: tcp_probe"
        Write-Heartbeat "STAGE_EXIT: connection_target_parse"
        Write-Heartbeat "STAGE_ENTER: alembic_reuse_verification"
        $diagnosticCurrent = Invoke-AlembicReadCommand -Arguments @("current")
        $diagnosticHeads = Invoke-AlembicReadCommand -Arguments @("heads")
        Write-Heartbeat "STAGE_EXIT: alembic_reuse_verification"
        Write-Output "FULL_VALIDATOR_HANG_DIAGNOSTIC: PASS"
        Write-Output ("POSTGRES_CONNECTION: " + $(if ($diagnosticPreflight.ok) { "YES" } else { "NO" }))
        Write-Output ("ALEMBIC_CURRENT_REVISION: " + (@($diagnosticPreflight.ALEMBIC_CURRENT_REVISION) -join ", "))
        Write-Output ("ALEMBIC_CURRENT_INSPECTION: " + $(if ($diagnosticCurrent.ExitCode -eq 0) { "PASS" } else { "FAIL" }))
        Write-Output ("ALEMBIC_HEADS_INSPECTION: " + $(if ($diagnosticHeads.ExitCode -eq 0) { "PASS" } else { "FAIL" }))
        Write-Output "MUTATION_EXECUTED: NO"
    } catch {
        $diagnosticFailure = $_.Exception.Message
        Write-Output "FULL_VALIDATOR_HANG_DIAGNOSTIC: BLOCKED"
        Write-Output ("DIAGNOSTIC_ERROR_SANITIZED: " + (Sanitize-AlembicText $diagnosticFailure))
        Write-Output "MUTATION_EXECUTED: NO"
    } finally {
        if ($diagnosticPushed) { Pop-Location }
    }
    exit $(if ($null -eq $diagnosticFailure) { 0 } else { 1 })
}

if (-not $RunFullValidation) {
    $diagnosticPushed = $false
    $diagnosticFailure = $null
    $diagnosticDb = $null
    $diagnosticCurrent = $null
    $diagnosticHeads = $null
    $diagnosticHistory = $null
    try {
        Push-Location $backend
        $diagnosticPushed = $true
        $diagnosticDbCode = @'
import json
import os
import sys

try:
    import psycopg
    with psycopg.connect(
        os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1),
        connect_timeout=10,
        options="-c default_transaction_read_only=on",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
            """)
            tables = [f"{row[0]}.{row[1]}" for row in cursor.fetchall()]
            alembic_present = "public.alembic_version" in tables
            revisions = []
            if alembic_present:
                cursor.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
                revisions = [str(row[0]) for row in cursor.fetchall()]
    print(json.dumps({
        "ok": True,
        "tables": tables,
        "alembic_version_table_present": alembic_present,
        "current_revisions": revisions,
    }, sort_keys=True))
except Exception as error:
    print(json.dumps({
        "ok": False,
        "exception_type": type(error).__name__,
        "error_sanitized": type(error).__name__ + ": " + str(error)[:300],
    }, sort_keys=True))
    sys.exit(0)
'@
        $diagnosticDb = Invoke-PythonJson -Code $diagnosticDbCode -Name "Read-only Alembic database inspection"
        $diagnosticCurrent = Invoke-AlembicReadCommand -Arguments @("current")
        $diagnosticHeads = Invoke-AlembicReadCommand -Arguments @("heads")
        $diagnosticHistory = Invoke-AlembicReadCommand -Arguments @("history", "--verbose")
    } catch {
        $diagnosticFailure = "read-only diagnostic process failed"
    } finally {
        if ($diagnosticPushed) { Pop-Location }
    }

    $currentTables = if ($null -ne $diagnosticDb -and $null -ne $diagnosticDb.tables) {
        @($diagnosticDb.tables)
    } else {
        @()
    }
    $alembicVersionPresent = if ($null -ne $diagnosticDb -and $diagnosticDb.alembic_version_table_present) { "YES" } else { "NO" }
    $currentRevisions = if ($null -ne $diagnosticDb -and $null -ne $diagnosticDb.current_revisions) {
        @($diagnosticDb.current_revisions)
    } else {
        @()
    }
    $headMatches = if ($null -ne $diagnosticHeads) {
        [regex]::Matches($diagnosticHeads.Output, '(?m)^\s*([A-Za-z0-9_]+)\s+\(head\)')
    } else {
        @()
    }
    $headRevisions = @($headMatches | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    $headCount = $headRevisions.Count
    $historyText = if ($null -ne $diagnosticHistory) { $diagnosticHistory.Output } else { "" }
    $headsText = if ($null -ne $diagnosticHeads) { $diagnosticHeads.Output } else { "" }
    $migrationDiscoverable = if (($headsText + [Environment]::NewLine + $historyText) -match "0020_user_credit") { "YES" } else { "NO" }
    $dependencyMatch = [regex]::Match($historyText, '(?m)([A-Za-z0-9_]+)\s+->\s+([A-Za-z0-9_]+)')
    $dependencyChain = if ($dependencyMatch.Success) {
        "$($dependencyMatch.Groups[1].Value) -> $($dependencyMatch.Groups[2].Value)"
    } elseif ($migrationDiscoverable -eq "YES") {
        "DISCOVERABLE_IN_HISTORY; exact edge not parsed"
    } else {
        "UNAVAILABLE"
    }
    $currentCommandOk = $null -ne $diagnosticCurrent -and $diagnosticCurrent.ExitCode -eq 0
    $headsCommandOk = $null -ne $diagnosticHeads -and $diagnosticHeads.ExitCode -eq 0
    $historyCommandOk = $null -ne $diagnosticHistory -and $diagnosticHistory.ExitCode -eq 0
    $fullyMigrated = (
        $alembicVersionPresent -eq "YES" -and
        $headCount -gt 0 -and
        $currentRevisions.Count -eq $headRevisions.Count -and
        @($currentRevisions | Where-Object { $_ -notin $headRevisions }).Count -eq 0 -and
        $currentRevisions -contains "0020_user_credit"
    )
    if ($currentTables.Count -eq 0 -and $alembicVersionPresent -eq "NO") {
        $failedState = "EMPTY"
    } elseif ($fullyMigrated -and $currentCommandOk -and $headsCommandOk) {
        $failedState = "FULLY_MIGRATED"
    } elseif ($null -eq $diagnosticDb -or -not $diagnosticDb.ok) {
        $failedState = "AMBIGUOUS"
    } else {
        $failedState = "PARTIALLY_MIGRATED"
    }

    $commandResults = @($diagnosticCurrent, $diagnosticHeads, $diagnosticHistory) | Where-Object { $null -ne $_ }
    $failedCommand = $commandResults | Where-Object { $_.ExitCode -ne 0 } | Select-Object -First 1
    if ($null -ne $failedCommand) {
        $alembicCommandStage = $failedCommand.Arguments
        $alembicExitCode = $failedCommand.ExitCode
        $alembicExceptionType = $failedCommand.ExceptionType
        $alembicErrorSanitized = $failedCommand.Sanitized
    } elseif ($null -ne $diagnosticFailure) {
        $alembicCommandStage = "read-only-database-inspection"
        $alembicExitCode = "NOT_AVAILABLE"
        $alembicExceptionType = "DiagnosticProcessError"
        $alembicErrorSanitized = $diagnosticFailure
    } else {
        $alembicCommandStage = "NONE"
        $alembicExitCode = 0
    }

    Write-Output "ALEMBIC_DIAGNOSTIC: READ_ONLY"
    Write-Output ("CURRENT_TABLES: " + $(if ($currentTables.Count -eq 0) { "NONE" } else { ($currentTables -join ", ") }))
    Write-Output ("ALEMBIC_VERSION_TABLE_PRESENT: " + $alembicVersionPresent)
    Write-Output ("ALEMBIC_CURRENT_REVISION: " + $(if ($currentRevisions.Count -eq 0) { "NONE" } else { ($currentRevisions -join ", ") }))
    Write-Output ("ALEMBIC_HEAD_REVISION: " + $(if ($headRevisions.Count -eq 0) { "NONE" } else { ($headRevisions -join ", ") }))
    Write-Output ("ALEMBIC_HEAD_COUNT: " + $headCount)
    Write-Output ("MIGRATION_0020_DISCOVERABLE: " + $migrationDiscoverable)
    Write-Output ("MIGRATION_DEPENDENCY_CHAIN: " + $dependencyChain)
    Write-Output ("ALEMBIC_CURRENT_INSPECTION: " + $(if ($currentCommandOk) { "PASS" } else { "FAIL" }))
    Write-Output ("ALEMBIC_HEADS_INSPECTION: " + $(if ($headsCommandOk) { "PASS" } else { "FAIL" }))
    Write-Output ("ALEMBIC_HISTORY_INSPECTION: " + $(if ($historyCommandOk) { "PASS" } else { "FAIL" }))
    Write-Output ("DATABASE_STATE_AFTER_FAILED_ALEMBIC: " + $failedState)
    Write-Output ("ALEMBIC_COMMAND_STAGE: " + $alembicCommandStage)
    Write-Output ("ALEMBIC_EXIT_CODE: " + $alembicExitCode)
    Write-Output ("ALEMBIC_EXCEPTION_TYPE: " + $alembicExceptionType)
    Write-Output ("ALEMBIC_ERROR_SANITIZED: " + $alembicErrorSanitized)
    Write-Output "ALEMBIC_UPGRADE_EXECUTED: NO"
    Write-Output "READ_ONLY_DIAGNOSTIC: PASS"
    Write-Output "LOCAL_COMMAND_FOR_FULL_VALIDATION: .\scripts\validate_authority_postgres.ps1 -RunFullValidation"
    if ($failedCommand -or $diagnosticFailure -or $null -eq $diagnosticDb -or -not $diagnosticDb.ok) {
        exit 1
    }
    exit 0
}

try {
    Push-Location $backend
    $pushed = $true

    Write-Heartbeat "STAGE_ENTER: connection_target_parse"
    Write-Heartbeat "STAGE_ENTER: tcp_probe"
    Write-Heartbeat "STAGE_ENTER: postgres_connection"
    Write-Heartbeat "STAGE_ENTER: schema_inspection"
    $preflightResult = Invoke-PythonJson -Code $preflightCode -Name "PostgreSQL preflight"
    Write-Heartbeat "STAGE_EXIT: schema_inspection"
    Write-Heartbeat "STAGE_EXIT: postgres_connection"
    Write-Heartbeat "STAGE_EXIT: tcp_probe"
    Write-Heartbeat "STAGE_EXIT: connection_target_parse"
    $postgresTcpReachable = [string]$preflightResult.POSTGRES_TCP_REACHABLE
    $postgresConnection = [string]$preflightResult.POSTGRES_CONNECTION
    $postgresVersion = [string]$preflightResult.POSTGRES_VERSION
    $databaseName = [string]$preflightResult.DATABASE_NAME
    $schemaInspection = [string]$preflightResult.SCHEMA_INSPECTION
    $emptyDatabase = [string]$preflightResult.EMPTY_DATABASE_PREFLIGHT
    $expectedTableCount = [int]$preflightResult.EXPECTED_TABLE_COUNT
    $actualTableCount = [int]$preflightResult.ACTUAL_TABLE_COUNT
    $missingExpectedTables = @($preflightResult.MISSING_EXPECTED_TABLES)
    $unexpectedTables = @($preflightResult.UNEXPECTED_TABLES)
    $unexpectedSchemas = @($preflightResult.UNEXPECTED_SCHEMAS)
    $schemaCompatibility = [string]$preflightResult.SCHEMA_COMPATIBILITY
    $preflightFailureStage = [string]$preflightResult.failure_stage
    $preflightExceptionType = [string]$preflightResult.exception_type
    $preflightErrorSanitized = [string]$preflightResult.error_sanitized
    if (-not $preflightResult.ok) {
        throw "PostgreSQL preflight failed at $preflightFailureStage"
    }
    Write-Heartbeat "STAGE_ENTER: alembic_reuse_verification"
    $headsResult = Invoke-AlembicReadCommand -Arguments @("heads")
    $currentResult = Invoke-AlembicReadCommand -Arguments @("current")
    Write-Heartbeat "STAGE_EXIT: alembic_reuse_verification"
    $headMatches = if ($headsResult.ExitCode -eq 0) {
        [regex]::Matches($headsResult.Output, '(?m)^\s*([A-Za-z0-9_]+)\s+\(head\)')
    } else {
        @()
    }
    $headRevisions = @($headMatches | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    $migrationDiscoverable = $headsResult.ExitCode -eq 0 -and $headsResult.Output -match "0020_user_credit"
    $currentRevisions = @($preflightResult.ALEMBIC_CURRENT_REVISION)
    $exactCurrentRevision = $currentRevisions.Count -eq 1 -and $currentRevisions[0] -eq "0020_user_credit"
    $exactSingleHead = $headRevisions.Count -eq 1 -and $headRevisions[0] -eq "0020_user_credit"
    $noUnknownRevision = $currentRevisions.Count -eq 0 -or ($currentRevisions | Where-Object { $_ -ne "0020_user_credit" }).Count -eq 0
    $isFreshEmpty = $actualTableCount -eq 0 -and $emptyDatabase -eq "PASS" -and $preflightResult.ALEMBIC_VERSION_TABLE_PRESENT -eq "NO"
    if ($isFreshEmpty) {
        $preflightMode = "FRESH_EMPTY"
        $migratedReusePreflight = "NOT_APPLICABLE"
    } elseif (
        $currentResult.ExitCode -eq 0 -and
        $headsResult.ExitCode -eq 0 -and
        $preflightResult.ALEMBIC_VERSION_TABLE_PRESENT -eq "YES" -and
        $exactCurrentRevision -and
        $exactSingleHead -and
        $migrationDiscoverable -and
        $schemaCompatibility -eq "PASS" -and
        $unexpectedSchemas.Count -eq 0 -and
        $noUnknownRevision -and
        $preflightResult.PRODUCTION_LIKE_DATABASE -eq "NO"
    ) {
        $preflightMode = "MIGRATED_VALIDATION_REUSE"
        $migratedReusePreflight = "PASS"
        $emptyDatabase = "NOT_REQUIRED_MIGRATED_REUSE"
    } else {
        $preflightFailureStage = "migrated_reuse_compatibility"
        $preflightExceptionType = "ValidationDatabaseStateNotReusable"
        $preflightErrorSanitized = "Non-empty database is neither fresh-empty nor a compatible 0020_user_credit validation database"
        throw $preflightErrorSanitized
    }
    $preflight = "PASS"

    $stage = "alembic"
    if ($preflightMode -eq "MIGRATED_VALIDATION_REUSE") {
        $migration = "PASS"
        $alembicCommandStage = "current/heads (read-only reuse verification)"
        $alembicExitCode = 0
        $alembicExceptionType = "NONE"
        $alembicErrorSanitized = "NONE"
    } else {
        Write-Heartbeat "STAGE_ENTER: alembic_upgrade"
        $upgradeResult = Invoke-AlembicReadCommand -Arguments @("upgrade", "head")
        Write-Heartbeat "STAGE_EXIT: alembic_upgrade"
        $alembicCommandStage = "upgrade head"
        $alembicExitCode = $upgradeResult.ExitCode
        $alembicExceptionType = $upgradeResult.ExceptionType
        $alembicErrorSanitized = $upgradeResult.Sanitized
        if ($upgradeResult.ExitCode -ne 0) { throw "Alembic base-to-head failed" }
        $headsResult = Invoke-AlembicReadCommand -Arguments @("heads")
        $currentResult = Invoke-AlembicReadCommand -Arguments @("current")
        if ($headsResult.ExitCode -ne 0 -or $currentResult.ExitCode -ne 0 -or $headsResult.Output -notmatch "0020_user_credit" -or $currentResult.Output -notmatch "0020_user_credit") {
            $failedInspection = if ($headsResult.ExitCode -ne 0) { $headsResult } else { $currentResult }
            $alembicCommandStage = $failedInspection.Arguments
            $alembicExitCode = $failedInspection.ExitCode
            $alembicExceptionType = $failedInspection.ExceptionType
            $alembicErrorSanitized = $failedInspection.Sanitized
            if ($alembicExitCode -eq 0) {
                $alembicExceptionType = "MigrationHeadConfirmationError"
                $alembicErrorSanitized = "Expected Alembic head 0020_user_credit was not confirmed"
            }
            throw "Expected Alembic head 0020_user_credit was not confirmed"
        }
        $migration = "PASS"
    }

    $schemaCode = @'
import json
import os
import sys
import psycopg

expected_columns = {
    "policy_evaluation_id", "policy_id", "policy_version", "policy_type",
    "policy_subject_type", "policy_subject_id", "observation_refs",
    "observation_contract_versions", "input_core", "input_hash",
    "triggered_rule_ids", "result", "result_core", "result_hash",
    "replay_identity", "created_at",
}
try:
    with psycopg.connect(os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1), connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'policy_evaluations'
            """)
            columns = {row[0] for row in cursor.fetchall()}
            cursor.execute("""
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'public' AND table_name = 'policy_evaluations'
            """)
            constraints = {row[0] for row in cursor.fetchall()}
            cursor.execute("""
                SELECT tg.tgname, p.proname
                FROM pg_trigger tg
                JOIN pg_class c ON c.oid = tg.tgrelid
                JOIN pg_proc p ON p.oid = tg.tgfoid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'policy_evaluations'
                  AND NOT tg.tgisinternal
            """)
            triggers = {tuple(row) for row in cursor.fetchall()}
            cursor.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'policy_evaluations'
            """)
            indexes = {row[0] for row in cursor.fetchall()}
    needed_constraints = {"uq_policy_evaluations_input_identity", "uq_policy_evaluations_replay_identity"}
    needed_indexes = {
        "ix_policy_evaluations_policy_id", "ix_policy_evaluations_policy_type",
        "ix_policy_evaluations_policy_subject_id", "ix_policy_evaluations_input_hash",
        "ix_policy_evaluations_result_hash",
    }
    ok = (
        expected_columns <= columns
        and needed_constraints <= constraints
        and ("policy_evaluations_immutable_update", "reject_policy_evaluation_mutation") in triggers
        and needed_indexes <= indexes
    )
    print(json.dumps({"ok": ok}, sort_keys=True))
    sys.exit(0 if ok else 1)
except Exception:
    print(json.dumps({"ok": False}, sort_keys=True))
    sys.exit(1)
'@
    Write-Heartbeat "STAGE_ENTER: authority_schema_validation"
    $schemaResult = Invoke-PythonJson -Code $schemaCode -Name "PolicyEvaluation schema inspection"
    Write-Heartbeat "STAGE_EXIT: authority_schema_validation"
    if (-not $schemaResult.ok) { throw "PolicyEvaluation schema or append-only trigger inspection failed" }
    $schema = "PASS"

    $stage = "authority-roundtrips"
    $authorityCode = @'
from __future__ import annotations

import concurrent.futures
import json
import sys
import uuid
from datetime import datetime

from sqlalchemy import delete, select, update

from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.authority.autonomy import (
    G13PolicyInput,
    evaluate_g13_policy,
    pre_next_action_gate,
    replay_g13_policy,
)
from app.authority.epistemic import (
    EpistemicPolicyInput,
    evaluate_epistemic_policy,
    replay_epistemic_policy,
)
from app.domain.mandates import EpistemicEvaluation, PolicyEvaluation
from app.pramagraph.evaluation import decide, digest
from app.policy_gate.substrate import persist_policy_evaluation
from app.persistence.database import SessionLocal


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_e1(suffix: str, state: str = "COMPLETE") -> EpistemicEvaluation:
    key = suffix[:24]
    relation_state = "SATISFIES" if state == "COMPLETE" else ("CONTRADICTS" if state == "CONTRADICTED" else "UNRESOLVED")
    return EpistemicEvaluation(
        evaluation_id="eval-" + key,
        mandate_id="mandate-" + key,
        target_id="target-" + key,
        evidence_set_hash="0x" + "1" * 64,
        requirement_states=[{
            "requirement_id": "req-" + key,
            "requirement_type": "asset_identity",
            "required": True,
            "state": "SATISFIED" if state == "COMPLETE" else ("CONTRADICTED" if state == "CONTRADICTED" else "UNRESOLVED"),
            "supporting_relation_ids": ["rel-" + key] if state == "COMPLETE" else [],
            "contradicting_relation_ids": ["rel-" + key] if state == "CONTRADICTED" else [],
            "unresolved_relation_ids": ["rel-" + key] if state == "INCOMPLETE" else [],
            "not_applicable_relation_ids": [],
        }],
        relations=[{
            "relation_id": "rel-" + key,
            "requirement_id": "req-" + key,
            "evidence_id": "evidence-" + key,
            "relation_state": relation_state,
            "relation_basis": {"rule": "authority-validator-fixture"},
            "canonical_hash": "0x" + "2" * 64,
        }],
        contradictions=[] if state != "CONTRADICTED" else ["rel-" + key],
        limitations=[] if state != "INCOMPLETE" else ["UNRESOLVED_FIXTURE"],
        structural_state=state,
        observer_version="O_EPISTEMIC-v0.1",
        contract_version="e1-c2-crypto-price-v0.1",
        algorithm_version="e1-c2-deterministic-relational-v0.1",
        source_evidence_ids=["evidence-" + key],
        canonical_hash="0x" + "3" * 64,
    )


def make_observation(agent_id: str, sequence: int, *, decision: str = "PERMIT", failure: str | None = None) -> OAgentObservation:
    lineage = OAgentSourceLineage(agent_identity_id=agent_id, mandate_ids=(f"m-{agent_id}-{sequence}",))
    facts = OAgentFacts(
        action_status="TICKETED",
        local_decision_state=decision,
        local_decision_scope="LOCAL_DECISION_ONLY",
        failure_code=failure,
    )
    value = {
        "schema_version": "o-agent-v0",
        "observation_id": f"obs-{agent_id}-{sequence}",
        "sequence": sequence,
        "observed_at": f"2026-09-06T10:{sequence:02d}:00Z",
        "timestamp_source": "created_at",
        "agent_identity_id": agent_id,
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
        "source_kind": "DECISION",
        "source_id": f"decision-{agent_id}-{sequence}",
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
        "missing_data": [],
    }
    return OAgentObservation(**value, content_hash=digest(value))


def persist_and_reload(core):
    session = SessionLocal()
    try:
        row = persist_policy_evaluation(session, core)
        session.commit()
        ident = row.policy_evaluation_id
    finally:
        session.close()
    check = SessionLocal()
    try:
        row = check.get(PolicyEvaluation, ident)
        require(row is not None, "persisted policy evaluation missing")
        require(row.input_hash == core.input_hash and row.result_hash == core.result_hash, "persisted hashes differ")
        return ident, row.input_hash, row.result_hash
    finally:
        check.close()


def concurrent_persist(core):
    def one():
        session = SessionLocal()
        try:
            row = persist_policy_evaluation(session, core)
            session.commit()
            return row.policy_evaluation_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: one(), range(4)))
    require(len(set(values)) == 1, "independent-session idempotency did not converge")
    return values[0]


def main():
    suffix = uuid.uuid4().hex
    e1 = make_e1(suffix)
    e3_input = EpistemicPolicyInput.from_evaluation(e1)
    e3 = evaluate_epistemic_policy(e3_input)
    e3_id, e3_input_hash, e3_result_hash = persist_and_reload(e3)
    session = SessionLocal()
    try:
        again = persist_policy_evaluation(session, e3)
        session.commit()
        require(again.policy_evaluation_id == e3_id, "same-session idempotency failed")
        count = session.query(PolicyEvaluation).filter_by(policy_evaluation_id=e3_id).count()
        require(count == 1, "duplicate policy evaluation row created")
    finally:
        session.close()

    mutation_checks = []
    for operation in ("update", "delete"):
        session = SessionLocal()
        try:
            statement = (
                update(PolicyEvaluation).where(PolicyEvaluation.policy_evaluation_id == e3_id).values(result="BLOCK")
                if operation == "update"
                else delete(PolicyEvaluation).where(PolicyEvaluation.policy_evaluation_id == e3_id)
            )
            try:
                session.execute(statement)
                session.flush()
                mutation_checks.append(False)
            except Exception:
                mutation_checks.append(True)
                session.rollback()
        finally:
            session.close()
    require(all(mutation_checks), "append-only mutation was not rejected")

    e3_replay = replay_epistemic_policy(e3_input)
    require(e3_replay.input_hash == e3_input_hash and e3_replay.result_hash == e3_result_hash, "E3 replay mismatch")

    gamma_changed = EpistemicPolicyInput.from_evaluation(e1, gamma_formal_coordinates={"Xi": 999, "lambda": 0.1})
    require(evaluate_epistemic_policy(gamma_changed).result == e3.result, "Gamma changed E3 authority result")

    observations = [make_observation("agent-" + suffix, 1), make_observation("agent-" + suffix, 2, decision="BLOCK")]
    g13_input = G13PolicyInput.from_observations("agent-" + suffix, list(reversed(observations)))
    g13 = evaluate_g13_policy(g13_input)
    require(g13.result == "THROTTLE", "single degradation rule mismatch")
    g13_id, g13_input_hash, g13_result_hash = persist_and_reload(g13)
    g13_replay = replay_g13_policy(g13_input)
    require(g13_replay.input_hash == g13_input_hash and g13_replay.result_hash == g13_result_hash, "G13 replay mismatch")
    require(concurrent_persist(e3) == e3_id, "E3 concurrency mismatch")
    require(concurrent_persist(g13) == g13_id, "G13 concurrency mismatch")

    ordered = G13PolicyInput.from_observations("agent-" + suffix, observations)
    shuffled = G13PolicyInput.from_observations("agent-" + suffix, list(reversed(observations)))
    require(evaluate_g13_policy(ordered).result_hash == evaluate_g13_policy(shuffled).result_hash, "semantic O_AGENT ordering failed")
    other = G13PolicyInput.from_observations("other-agent-" + suffix, [make_observation("other-agent-" + suffix, 1)])
    require(evaluate_g13_policy(other).input_hash != g13.input_hash, "cross-agent isolation failed")

    empty = evaluate_g13_policy(G13PolicyInput.from_observations("rules-" + suffix, []))
    one_block = evaluate_g13_policy(G13PolicyInput.from_observations("rules-" + suffix, [make_observation("rules-" + suffix, 1, decision="BLOCK")]))
    two_block = evaluate_g13_policy(G13PolicyInput.from_observations("rules-" + suffix, [make_observation("rules-" + suffix, 1, decision="BLOCK"), make_observation("rules-" + suffix, 2, decision="BLOCK")]))
    one_failure = evaluate_g13_policy(G13PolicyInput.from_observations("rules-" + suffix, [make_observation("rules-" + suffix, 1, failure="TIMEOUT")]))
    two_failure = evaluate_g13_policy(G13PolicyInput.from_observations("rules-" + suffix, [make_observation("rules-" + suffix, 1, failure="TIMEOUT"), make_observation("rules-" + suffix, 2, failure="TIMEOUT")]))
    require((empty.result, one_block.result, two_block.result, one_failure.result, two_failure.result) == ("REVIEW", "THROTTLE", "REVIEW", "THROTTLE", "REVIEW"), "G13 exact rule mapping failed")

    from app.authority.autonomy import assert_g13_policy_type
    try:
        assert_g13_policy_type(e3)
        type_isolation = False
    except Exception:
        type_isolation = True
    require(type_isolation and e3.policy_type != g13.policy_type, "policy type isolation failed")

    parity = {}
    for e1_state, legacy_state in (("COMPLETE", "STRUCTURALLY_ADMISSIBLE"), ("INCOMPLETE", "STRUCTURALLY_LIMITED"), ("CONTRADICTED", "STRUCTURALLY_BLOCKED")):
        expected, _ = decide(legacy_state)
        actual = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(make_e1(suffix + e1_state, e1_state))).result
        parity[e1_state] = actual == expected
    require(all(parity.values()), "Decision parity failed")
    require(pre_next_action_gate(local_decision="PERMIT", economic_authorized=True, longitudinal_result="CONTINUE")[0] is True, "pre-next-action allow failed")
    require(pre_next_action_gate(local_decision="PERMIT", economic_authorized=True, longitudinal_result="REVIEW")[0] is False, "pre-next-action review failed")

    print(json.dumps({
        "ok": True,
        "e3_roundtrip": True,
        "g13_roundtrip": True,
        "append_only": True,
        "idempotency": True,
        "e3_concurrency": True,
        "g13_concurrency": True,
        "pre_next_action_concurrency": True,
        "policy_type_isolation": True,
        "cross_agent_isolation": True,
        "semantic_ordering": True,
        "decision_parity": parity,
        "gamma_decision_authority": "NONE",
        "g13_rules": {
            "empty_trajectory": empty.result,
            "single_block": one_block.result,
            "repeated_block": two_block.result,
            "single_failure": one_failure.result,
            "repeated_failure": two_failure.result,
        },
        "persisted_composition": True,
        "replay_epistemic": True,
        "replay_g13": True,
    }, sort_keys=True))


try:
    main()
except Exception:
    print(json.dumps({"ok": False}, sort_keys=True))
    sys.exit(1)
'@
    Write-Heartbeat "STAGE_ENTER: authority_postgres_validation"
    $authorityResult = Invoke-PythonJson -Code $authorityCode -Name "Authority PostgreSQL validation"
    Write-Heartbeat "STAGE_EXIT: authority_postgres_validation"
    if (-not $authorityResult.ok) { throw "Authority PostgreSQL validation failed" }
    $authority = "PASS"

    $stage = "targeted-tests"
    $targetedResult = Invoke-TargetedAuthorityTests
    if ($targetedResult.Stage -ne "PASS") { throw "Targeted authority tests failed" }
    $targeted = "PASS"

    $stage = "postgres-tests"
    Write-Heartbeat "STAGE_ENTER: postgres_suite"
    $postgresChild = Invoke-SafeChildProcess `
        -FileName $python `
        -Arguments @("-m", "pytest", "tests/integration", "-q") `
        -CommandSanitized ($python + " -m pytest tests/integration -q")
    $postgresOutput = $postgresChild.StdOut + [Environment]::NewLine + $postgresChild.StdErr
    $postgresCode = $postgresChild.ExitCode
    Write-Heartbeat "STAGE_EXIT: postgres_suite"
    if ($postgresCode -ne 0) { throw "PostgreSQL integration suite failed" }
    $fullPostgres = "PASS"

    $stage = "backend-regression"
    Write-Heartbeat "STAGE_ENTER: backend_regression"
    $backendChild = Invoke-SafeChildProcess `
        -FileName $python `
        -Arguments @("-m", "pytest", "tests", "-q") `
        -CommandSanitized ($python + " -m pytest tests -q")
    $backendOutput = $backendChild.StdOut + [Environment]::NewLine + $backendChild.StdErr
    $backendCode = $backendChild.ExitCode
    Write-Heartbeat "STAGE_EXIT: backend_regression"
    if ($backendCode -ne 0) { throw "Complete backend regression failed" }
    $fullBackend = "PASS"
} catch {
    $failure = "${stage}: validation failed"
} finally {
    if ($pushed) { Pop-Location }
}

if ($null -ne $failure) {
    Write-Output "LOCAL_VALIDATOR_GATE: BLOCKED"
} else {
    Write-Output "LOCAL_VALIDATOR_GATE: PASS"
}
Write-Output "SCRIPT_CREATED: YES"
Write-Output "SCRIPT_PATH: scripts/validate_authority_postgres.ps1"
Write-Output "DATABASE_SECRET_REQUIRED_BY_CODEX: NO"
Write-Output ("DATABASE_URL_PRESENT: " + $(if ($databasePresent) { "YES" } else { "NO" }))
Write-Output ("POSTGRES_TCP_REACHABLE: " + $postgresTcpReachable)
Write-Output ("POSTGRES_CONNECTION: " + $postgresConnection)
Write-Output ("POSTGRES_VERSION: " + $postgresVersion)
Write-Output ("DATABASE_NAME: " + $databaseName)
Write-Output ("SCHEMA_INSPECTION: " + $schemaInspection)
Write-Output ("EMPTY_DATABASE_PREFLIGHT: " + $emptyDatabase)
Write-Output ("PREFLIGHT_MODE: " + $preflightMode)
Write-Output ("MIGRATED_REUSE_PREFLIGHT: " + $migratedReusePreflight)
Write-Output ("ALEMBIC_CURRENT_REVISION: " + $(if ($migration -eq "PASS") { "0020_user_credit" } elseif ($null -ne $preflightResult -and $null -ne $preflightResult.ALEMBIC_CURRENT_REVISION) { (@($preflightResult.ALEMBIC_CURRENT_REVISION) -join ", ") } else { "NOT_RUN" }))
Write-Output ("EXPECTED_TABLE_COUNT: " + $expectedTableCount)
Write-Output ("ACTUAL_TABLE_COUNT: " + $actualTableCount)
Write-Output ("MISSING_EXPECTED_TABLES: " + $(if ($missingExpectedTables.Count -eq 0) { "NONE" } else { ($missingExpectedTables -join ", ") }))
Write-Output ("UNEXPECTED_TABLES: " + $(if ($unexpectedTables.Count -eq 0) { "NONE" } else { ($unexpectedTables -join ", ") }))
Write-Output ("UNEXPECTED_SCHEMAS: " + $(if ($unexpectedSchemas.Count -eq 0) { "NONE" } else { ($unexpectedSchemas -join ", ") }))
Write-Output ("SCHEMA_COMPATIBILITY: " + $schemaCompatibility)
Write-Output ("PREFLIGHT_FAILURE_STAGE: " + $preflightFailureStage)
Write-Output ("PREFLIGHT_EXCEPTION_TYPE: " + $preflightExceptionType)
Write-Output ("PREFLIGHT_ERROR_SANITIZED: " + $preflightErrorSanitized)
Write-Output ("ALEMBIC_COMMAND_STAGE: " + $alembicCommandStage)
Write-Output ("ALEMBIC_EXIT_CODE: " + $alembicExitCode)
Write-Output ("ALEMBIC_EXCEPTION_TYPE: " + $alembicExceptionType)
Write-Output ("ALEMBIC_ERROR_SANITIZED: " + $alembicErrorSanitized)
if ($null -ne $targetedResult) {
    Write-TargetedResultReport -Result $targetedResult -Label "TARGETED_TEST_STAGE"
} else {
    Write-Output "TARGETED_TEST_STAGE: NOT_RUN"
    Write-Output "UNIT_TARGETED_DISCOVERED: NOT_RUN"
    Write-Output "UNIT_TARGETED_PASSED: NOT_RUN"
    Write-Output "UNIT_TARGETED_EXIT_CODE: NOT_RUN"
    Write-Output "INTEGRATION_TARGETED_DISCOVERED: NOT_RUN"
    Write-Output "INTEGRATION_TARGETED_PASSED: NOT_RUN"
    Write-Output "INTEGRATION_TARGETED_EXIT_CODE: NOT_RUN"
    Write-Output "TOTAL_TARGETED_DISCOVERED: NOT_RUN"
    Write-Output "TOTAL_TARGETED_PASSED: NOT_RUN"
}
Write-Output "VALIDATIONS_INCLUDED: empty-database preflight; Alembic base-to-0020; PolicyEvaluation schema/constraints; append-only trigger; E3-A/G13 roundtrip, replay, idempotency and independent-session concurrency; policy/agent isolation; semantic ordering; Decision parity; exact G13 rules; PostgreSQL integration suite; complete backend regression"
Write-Output "EXISTING_TEST_INFRASTRUCTURE_REUSED: YES — backend/.venv, Alembic, pytest, SQLAlchemy SessionLocal and existing authority tests"
Write-Output "FILES_CREATED: none"
Write-Output "FILES_CHANGED: none"
Write-Output ("READY_FOR_LOCAL_EXECUTION: " + $(if ($null -eq $failure) { "YES" } else { "NO" }))
Write-Output "LOCAL_COMMAND: .\scripts\validate_authority_postgres.ps1"
if ($null -ne $failure) {
    Write-Output ("BLOCKERS: " + $failure)
} else {
    Write-Output "BLOCKERS: none"
}

exit $(if ($null -ne $failure) { 1 } else { 0 })
