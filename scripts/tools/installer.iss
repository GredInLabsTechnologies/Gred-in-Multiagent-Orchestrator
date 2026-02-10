[Setup]
AppName=Gred Repo Orchestrator
AppVersion=1.0.0
DefaultDirName={autopf}\GredRepoOrchestrator
DefaultGroupName=Gred Repo Orchestrator
UninstallDisplayIcon={app}\orchestrator_icon.ico
Compression=lzma2
SolidCompression=yes
OutputDir=setup
OutputBaseFilename=Gred_Orchestrator_Setup
SetupIconFile=..\orchestrator_icon.ico
PrivilegesRequired=admin

[Files]
; Core Files
Source: "..\tools\gimo_server\*"; DestDir: "{app}\tools\gimo_server"; Flags: recursesubdirs
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Flags: recursesubdirs
Source: "..\.env"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\orchestrator_icon.ico"; DestDir: "{app}"

; Dashboard
Source: "..\tools\orchestrator_dashboard\dist\*"; DestDir: "{app}\dashboard"; Flags: recursesubdirs

[Icons]
Name: "{group}\Gred Orchestrator Dashboard"; Filename: "{app}\dashboard\index.html"
Name: "{group}\Start Orchestrator Service"; Filename: "{app}\scripts\start_orch.cmd"; IconFilename: "{app}\orchestrator_icon.ico"
Name: "{commondesktop}\Gred Orchestrator"; Filename: "{app}\scripts\start_orch.cmd"; IconFilename: "{app}\orchestrator_icon.ico"

[Run]
; Crear servicio si no existe (idempotente)
Filename: "{sys}\cmd.exe"; Parameters: "/c sc.exe query ""GILOrchestrator"" >nul 2>&1 || sc.exe create ""GILOrchestrator"" binPath= """"{app}\scripts\Gred_Orchestrator.exe"""" start= auto obj= ""LocalSystem"""; Flags: runhidden waituntilterminated

; Arrancar servicio
Filename: "{sys}\cmd.exe"; Parameters: "/c sc.exe start ""GILOrchestrator"""; Flags: runhidden waituntilterminated

Filename: "{app}\scripts\configure_gil_service_user_elevated.cmd"; Description: "Configurar servicio como LocalSystem"; Flags: runascurrentuser postinstall
