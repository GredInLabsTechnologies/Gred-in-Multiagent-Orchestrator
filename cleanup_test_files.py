import shutil
from pathlib import Path

root = Path(".")
logs_dir = root / "logs"
logs_dir.mkdir(exist_ok=True)

patterns = ["test_*.txt", "test_*.log", "pytest_*.txt", "pytest_*.log"]
moved_count = 0

print(f"Cleaning root directory into {logs_dir}...")

for pattern in patterns:
    for file_path in root.glob(pattern):
        if file_path.is_file():
            dest = logs_dir / file_path.name
            try:
                # Handle overwrites if necessary
                if dest.exists():
                    dest.unlink()
                shutil.move(str(file_path), str(dest))
                print(f"Moved: {file_path.name}")
                moved_count += 1
            except Exception as e:
                print(f"Error moving {file_path.name}: {e}")

print(f"Finished. Moved {moved_count} files.")
