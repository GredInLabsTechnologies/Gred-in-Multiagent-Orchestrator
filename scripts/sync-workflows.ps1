$source = ".agent/workflows"
$targets = @(
    ".clinerules/workflows",
    ".claude/commands"
)

if (!(Test-Path $source)) {
    Write-Host "❌ Source folder not found: $source" -ForegroundColor Red
    exit 1
}

foreach ($target in $targets) {
    if (!(Test-Path $target)) {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
    }
    Copy-Item -Path "$source\*.md" -Destination $target -Force
    Write-Host "✅ Sincronizado: $source -> $target" -ForegroundColor Green
}

Write-Host "✅ Sincronización completada." -ForegroundColor Green
