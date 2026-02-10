# Launch Claude CLI in a new window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\..\..'; python scripts\tools\claude_cli.py"
