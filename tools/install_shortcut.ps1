# Creates the "N2 Daily" desktop shortcut (and a Start menu entry) pointing at launch.pyw.
$ErrorActionPreference = 'Stop'
$appDir = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $appDir '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Missing $pythonw - run 'uv venv --python 3.14 .venv' in $appDir first." }

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) '')
)
foreach ($folder in $targets) {
    $shortcut = $shell.CreateShortcut((Join-Path $folder 'N2 Daily.lnk'))
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = '"' + (Join-Path $appDir 'launch.pyw') + '"'
    $shortcut.WorkingDirectory = $appDir
    $shortcut.IconLocation = (Join-Path $appDir 'assets\n2daily.ico') + ',0'
    $shortcut.Description = 'Daily JLPT N2 mini mock test and vocab review'
    $shortcut.Save()
    Write-Output "Created $($shortcut.FullName)"
}
