param(
    [string]$Account,
    [string]$Sid = ""
)

if ([string]::IsNullOrWhiteSpace($Sid)) {
    $localAccount = if ($Account -match "^\\\\") { $Account } else { ".\\$Account" }
    $sid = (New-Object System.Security.Principal.NTAccount($localAccount)).Translate([System.Security.Principal.SecurityIdentifier]).Value
}
else {
    $sid = $Sid
}
$cfgPath = Join-Path $env:TEMP "secpol.cfg"
$dbPath = Join-Path $env:TEMP "secpol.sdb"

secedit /export /cfg $cfgPath | Out-Null
$cfg = Get-Content $cfgPath

$right = "SeServiceLogonRight"
if ($cfg -notmatch "^$right\s*=") {
    Add-Content $cfgPath "$right = *$sid"
}
else {
    $updated = $cfg -replace "^$right\s*=\s*(.*)$", "$right = $1,*$sid"
    Set-Content $cfgPath $updated
}

secedit /configure /db $dbPath /cfg $cfgPath /areas USER_RIGHTS | Out-Null
gpupdate /force | Out-Null

Write-Host "Granted '$right' to $Account ($sid)."
