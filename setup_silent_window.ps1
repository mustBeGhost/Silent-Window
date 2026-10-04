param([switch]$WithTests, [switch]$SkipDatabaseSetup)
$ErrorActionPreference = 'Stop'
$taskPreviousDirectory = Get-Location
try {
    Set-Location -LiteralPath $PSScriptRoot
    $taskPortsBusy = $false
    foreach ($taskPort in @(8001, 5173)) {
        $taskPortClient = [Net.Sockets.TcpClient]::new()
        try {
            $taskConnection = $taskPortClient.ConnectAsync('127.0.0.1', $taskPort)
            if ($taskConnection.Wait(500) -and $taskPortClient.Connected) { $taskPortsBusy = $true }
        } catch { } finally { $taskPortClient.Dispose() }
    }
    if ($taskPortsBusy) {
        throw 'Stop the Silent Window servers before installing packages. No files were changed.'
    }
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'Install Node.js 22 or newer with npm, then try again.'
    }
    $taskNodeVersion = & node --version
    if ($LASTEXITCODE -ne 0 -or [int]($taskNodeVersion.TrimStart('v').Split('.')[0]) -lt 22) {
        throw 'Use Node.js 22 or newer before installing frontend packages.'
    }
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.11 -m venv .venv }
        else { & python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 and try again.' }
    }
    & .venv\Scripts\python.exe -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.11 or newer. Python 3.11 is the tested version.' }
    $taskRequirements = if ($WithTests) { 'requirements-dev.txt' } else { 'requirements.txt' }
    & .venv\Scripts\python.exe -m pip install -r $taskRequirements -c requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python packages could not be installed.' }
    Push-Location -LiteralPath frontend
    try { & npm ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend packages could not be installed.' } }
    finally { Pop-Location }
    & .venv\Scripts\python.exe -m scripts.check_installation --skip-database
    if ($LASTEXITCODE -ne 0) { throw 'Restore the required patient and saved model files before database setup.' }
    if (-not $SkipDatabaseSetup) {
        & .venv\Scripts\python.exe -m scripts.check_database
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Checking MySQL setup. Existing databases will not be overwritten.'
            & .venv\Scripts\python.exe -m scripts.configure_mysql --host 127.0.0.1 --port 3306 --username root
            if ($LASTEXITCODE -ne 0) { throw 'Database setup did not finish. For an existing installation, follow the migration instructions.' }
        }
        & .venv\Scripts\python.exe -m scripts.check_installation
        if ($LASTEXITCODE -ne 0) { throw 'Installation checks did not pass.' }
    }
    Write-Host 'Setup finished. Use run_silent_window.bat to start the website.'
} finally { Set-Location -LiteralPath $taskPreviousDirectory }
