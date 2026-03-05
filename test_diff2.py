import os
import shutil
from pathlib import Path
from tools.gimo_server.services.diff_application_service import DiffApplicationService

worktree = Path("temp_worktree2")
worktree.mkdir(exist_ok=True)
test_file = worktree / "test.py"
test_file.write_text("def hello():\r\n    print('world')\r\n", encoding="utf-8")

# Agent content with a patch with \r\n and varying characters
agent_content = "Here is the fix:\r\n\r\nFile: test.py\r\n<<<<<<< SEARCH\r\n    print('world')\r\n=======\r\n    print('GIMO')\r\n>>>>>>> REPLACE\r\n"

print(f"Before: {repr(test_file.read_text())}")
DiffApplicationService.apply(str(worktree), agent_content)
print(f"After: {repr(test_file.read_text())}")

# Cleanup
shutil.rmtree(worktree)
print("Done.")
