param(
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$Files
)

# Windows clipboard file-drop operations must run in an STA apartment.
# When launched from WSL/OpenClaw without -STA, SetFileDropList may appear to
# succeed but LINE cannot paste the files. Relaunch ourselves with -STA.
if ([System.Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') {
  $script = $MyInvocation.MyCommand.Path
  $quotedFiles = @($Files | ForEach-Object { '"' + ($_ -replace '"', '`"') + '"' })
  $argLine = @('-STA', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $script + '"')) + $quotedFiles
  $p = Start-Process -FilePath powershell.exe -ArgumentList $argLine -Wait -PassThru
  exit $p.ExitCode
}

Add-Type -AssemblyName System.Windows.Forms
$collection = New-Object System.Collections.Specialized.StringCollection
foreach ($file in $Files) {
  if (-not [System.IO.File]::Exists($file)) {
    throw "File not found: $file"
  }
  [void]$collection.Add([System.IO.Path]::GetFullPath($file))
}
[System.Windows.Forms.Clipboard]::SetFileDropList($collection)
Write-Output ("Copied {0} file(s) to Windows clipboard." -f $collection.Count)
