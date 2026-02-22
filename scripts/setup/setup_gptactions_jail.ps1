#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Configuración del jail de filesystem para GPT Actions en Windows.

.DESCRIPTION
    Crea el usuario de servicio gimo-actions con acceso EXCLUSIVO al jail.
    Aplica ACLs estrictas para garantizar que gimo-actions NO puede:
      - Leer o escribir fuera del jail
      - Acceder a .env, .ssh, secretos, ni al repo principal
      - Elevar privilegios (SeDebugPrivilege, SeImpersonatePrivilege)
      - Pertenece a cualquier grupo con permisos elevados

    Crea la estructura de directorios del jail y configura los permisos.

.PARAMETER JailRoot
    Ruta raíz del jail (default: ..\worktrees\gptactions relativo al repo)

.PARAMETER RepoRoot
    Ruta raíz del repositorio

.PARAMETER UserName
    Nombre del usuario de servicio (default: gimo-actions)

.PARAMETER UserPassword
    Contraseña del usuario de servicio (auto-generada si no se especifica)

.EXAMPLE
    .\setup_gptactions_jail.ps1 -RepoRoot "C:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator"

.NOTES
    Este script debe ejecutarse UNA SOLA VEZ durante el setup inicial.
    Requiere permisos de administrador.
#>

param(
    [string]$JailRoot = "",
    [string]$RepoRoot = "",
    [string]$UserName = "gimo-actions",
    [string]$UserPassword = ""
)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------------
# Banner
# ------------------------------------------------------------------
Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " GIMO GPT Actions Jail Setup" -ForegroundColor Cyan
Write-Host " Separation of Duties + Least Privilege" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------
# Resolver rutas
# ------------------------------------------------------------------
if (-not $RepoRoot) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path "$ScriptDir\..\.." ).Path
}

if (-not $JailRoot) {
    $JailRoot = Join-Path (Split-Path -Parent $RepoRoot) "worktrees\gptactions"
}

Write-Host "Configuración:" -ForegroundColor Yellow
Write-Host "  Repo root:  $RepoRoot"
Write-Host "  Jail root:  $JailRoot"
Write-Host "  Usuario:    $UserName"
Write-Host ""

# ------------------------------------------------------------------
# Verificar que no existe el usuario (idempotente)
# ------------------------------------------------------------------
$existingUser = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
if ($existingUser) {
    Write-Host "⚠️  El usuario $UserName ya existe." -ForegroundColor Yellow
    $confirm = Read-Host "¿Resetear permisos y continuar? (S/N)"
    if ($confirm -ne "S" -and $confirm -ne "s") {
        Write-Host "Operación cancelada." -ForegroundColor Red
        exit 0
    }
} else {
    # Crear usuario con contraseña aleatoria si no se especificó
    if (-not $UserPassword) {
        $UserPassword = [System.Web.Security.Membership]::GeneratePassword(32, 8)
        Write-Host "  Contraseña auto-generada (guárdala en un gestor de contraseñas):" -ForegroundColor Yellow
        Write-Host "  $UserPassword" -ForegroundColor Gray
        Write-Host ""
    }

    $SecurePassword = ConvertTo-SecureString $UserPassword -AsPlainText -Force
    New-LocalUser -Name $UserName `
                  -Password $SecurePassword `
                  -FullName "GIMO GPT Actions Service" `
                  -Description "Usuario de servicio con acceso mínimo al jail de GPT Actions" `
                  -PasswordNeverExpires `
                  -UserMayNotChangePassword | Out-Null

    Write-Host "✓ Usuario creado: $UserName" -ForegroundColor Green
}

# ------------------------------------------------------------------
# Eliminar membresías en grupos elevados
# ------------------------------------------------------------------
Write-Host "Verificando grupos del usuario..." -ForegroundColor Yellow

$dangerousGroups = @("Administrators", "Power Users", "Remote Desktop Users",
                     "Network Configuration Operators", "Backup Operators")

foreach ($group in $dangerousGroups) {
    try {
        $members = Get-LocalGroupMember -Group $group -ErrorAction SilentlyContinue
        if ($members -and ($members.Name -contains "$env:COMPUTERNAME\$UserName")) {
            Remove-LocalGroupMember -Group $group -Member $UserName -ErrorAction SilentlyContinue
            Write-Host "  ✓ Removido de grupo: $group" -ForegroundColor Green
        }
    } catch {
        # El grupo puede no existir
    }
}

Write-Host "✓ Membresías en grupos elevados eliminadas" -ForegroundColor Green

# ------------------------------------------------------------------
# Crear estructura del jail
# ------------------------------------------------------------------
Write-Host ""
Write-Host "Creando estructura del jail..." -ForegroundColor Yellow

$JailDirs = @(
    $JailRoot,
    "$JailRoot\patches",
    "$JailRoot\archive",
    "$JailRoot\manifest"
)

foreach ($dir in $JailDirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  ✓ Creado: $dir" -ForegroundColor Green
    } else {
        Write-Host "  → Ya existe: $dir" -ForegroundColor Gray
    }
}

# ------------------------------------------------------------------
# Configurar ACLs del jail
# ------------------------------------------------------------------
Write-Host ""
Write-Host "Configurando ACLs del jail..." -ForegroundColor Yellow

# Deshabilitar herencia y resetear ACL en el jail root
$JailAcl = New-Object System.Security.AccessControl.DirectorySecurity
$JailAcl.SetAccessRuleProtection($true, $false)  # Disable inheritance, remove inherited

# SYSTEM: Full Control (para el SO)
$SystemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "SYSTEM",
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$JailAcl.AddAccessRule($SystemRule)

# Administrators: Full Control (para el admin humano)
$AdminRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "Administrators",
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$JailAcl.AddAccessRule($AdminRule)

# gimo-actions: ReadAndExecute + Write en patches/ ONLY (aplicamos abajo)
# En el jail root, solo ReadAndExecute (para que pueda listar)
$GimoRootRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "$env:COMPUTERNAME\$UserName",
    "ReadAndExecute, ListDirectory",
    "None",
    "None",
    "Allow"
)
$JailAcl.AddAccessRule($GimoRootRule)

Set-Acl -Path $JailRoot -AclObject $JailAcl
Write-Host "  ✓ ACL del jail root configurada" -ForegroundColor Green

# patches/: gimo-actions tiene Modify (lectura + escritura + borrado)
$PatchesPath = "$JailRoot\patches"
$PatchesAcl = New-Object System.Security.AccessControl.DirectorySecurity
$PatchesAcl.SetAccessRuleProtection($true, $false)

foreach ($rule in @($SystemRule, $AdminRule)) {
    $PatchesAcl.AddAccessRule($rule)
}

$GimoPatchRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "$env:COMPUTERNAME\$UserName",
    "Modify",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$PatchesAcl.AddAccessRule($GimoPatchRule)

Set-Acl -Path $PatchesPath -AclObject $PatchesAcl
Write-Host "  ✓ ACL de patches/ configurada (gimo-actions: Modify)" -ForegroundColor Green

# manifest/: gimo-actions solo ReadAndExecute
$ManifestPath = "$JailRoot\manifest"
$ManifestAcl = New-Object System.Security.AccessControl.DirectorySecurity
$ManifestAcl.SetAccessRuleProtection($true, $false)

foreach ($rule in @($SystemRule, $AdminRule)) {
    $ManifestAcl.AddAccessRule($rule)
}

$GimoManifestRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "$env:COMPUTERNAME\$UserName",
    "ReadAndExecute, ListDirectory",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$ManifestAcl.AddAccessRule($GimoManifestRule)

Set-Acl -Path $ManifestPath -AclObject $ManifestAcl
Write-Host "  ✓ ACL de manifest/ configurada (gimo-actions: ReadOnly)" -ForegroundColor Green

# ------------------------------------------------------------------
# DENEGAR acceso del usuario al repo principal y a datos sensibles
# ------------------------------------------------------------------
Write-Host ""
Write-Host "Configurando DENY explícitos en directorios sensibles..." -ForegroundColor Yellow

$SensitivePaths = @(
    $RepoRoot,
    "$env:USERPROFILE\.ssh",
    "$env:USERPROFILE\.aws",
    "$env:USERPROFILE\.azure"
)

foreach ($path in $SensitivePaths) {
    if (Test-Path $path) {
        try {
            $acl = Get-Acl -Path $path
            $denyRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                "$env:COMPUTERNAME\$UserName",
                "FullControl",
                "ContainerInherit,ObjectInherit",
                "None",
                "Deny"
            )
            $acl.AddAccessRule($denyRule)
            Set-Acl -Path $path -AclObject $acl
            Write-Host "  ✓ DENY aplicado en: $path" -ForegroundColor Green
        } catch {
            Write-Host "  ⚠️  No se pudo aplicar DENY en: $path — $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}

# ------------------------------------------------------------------
# Verificar privilegios del usuario (deben estar vacíos)
# ------------------------------------------------------------------
Write-Host ""
Write-Host "Verificando privilegios del usuario..." -ForegroundColor Yellow

try {
    $rights = & secedit /export /cfg "$env:TEMP\secpol_temp.cfg" 2>&1
    $content = Get-Content "$env:TEMP\secpol_temp.cfg" -ErrorAction SilentlyContinue
    $dangerousPrivs = @(
        "SeDebugPrivilege",
        "SeImpersonatePrivilege",
        "SeTcbPrivilege",
        "SeLoadDriverPrivilege",
        "SeSystemEnvironmentPrivilege",
        "SeBackupPrivilege",
        "SeRestorePrivilege"
    )
    foreach ($priv in $dangerousPrivs) {
        $line = $content | Where-Object { $_ -match $priv }
        if ($line -and $line -match $UserName) {
            Write-Host "  ⚠️  ADVERTENCIA: $UserName tiene $priv — eliminar manualmente" -ForegroundColor Red
        }
    }
    Remove-Item "$env:TEMP\secpol_temp.cfg" -ErrorAction SilentlyContinue
} catch {
    Write-Host "  (No se pudo verificar secedit — verificar manualmente)" -ForegroundColor Yellow
}

Write-Host "✓ Verificación de privilegios completada" -ForegroundColor Green

# ------------------------------------------------------------------
# Resumen y próximos pasos
# ------------------------------------------------------------------
Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Setup completado exitosamente" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "PRÓXIMOS PASOS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. Sincronizar IPs de OpenAI:" -ForegroundColor White
Write-Host "     python scripts/setup/sync_openai_ips.py" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Generar claves de attestation:" -ForegroundColor White
Write-Host "     python -m tools.patch_validator.attestation --generate-keys" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. Asegurar la clave privada (SOLO el usuario validador debe leerla):" -ForegroundColor White
Write-Host "     icacls tools\patch_validator\keys\attestation_private.pem /inheritance:r" -ForegroundColor Gray
Write-Host "     icacls tools\patch_validator\keys\attestation_private.pem /grant:r `"$env:USERNAME:(R)`"" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. Actualizar manifest de archivos legibles:" -ForegroundColor White
Write-Host "     Edita: $JailRoot\manifest\readable_files.json" -ForegroundColor Gray
Write-Host ""
Write-Host "  5. Iniciar el gateway (como usuario $UserName):" -ForegroundColor White
Write-Host "     Configura GPTGW_TOKEN en el entorno de $UserName" -ForegroundColor Gray
Write-Host "     python -m tools.gptactions_gateway.main" -ForegroundColor Gray
Write-Host ""
Write-Host "  6. Añadir al Task Scheduler (sincronización diaria de IPs):" -ForegroundColor White
Write-Host "     schtasks /create /tn `"GIMO-SyncOpenAIIPs`" /tr `"python $RepoRoot\scripts\setup\sync_openai_ips.py`" /sc daily /st 03:00" -ForegroundColor Gray
Write-Host ""
Write-Host "CHECKLIST DE VERIFICACIÓN:" -ForegroundColor Yellow
Write-Host "  [ ] gimo-actions solo puede escribir en $JailRoot\patches" -ForegroundColor White
Write-Host "  [ ] gimo-actions NO puede leer $RepoRoot" -ForegroundColor White
Write-Host "  [ ] gimo-actions NO pertenece a Administrators" -ForegroundColor White
Write-Host "  [ ] IP allowlist actualizado (< 12h)" -ForegroundColor White
Write-Host "  [ ] Clave privada de attestation con ACL 600" -ForegroundColor White
Write-Host "  [ ] Gateway corriendo en puerto 9326 (no 9325)" -ForegroundColor White
Write-Host ""
