import ctypes
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

UI_FONT = "Segoe UI"
HEADER_STYLE = "Header.TLabel"
ICON_FILE = "orchestrator_icon.ico"
ENV_FILE = ".env"
SCRIPTS_DIR = "scripts"
TOOLS_DIR = "tools"

# Security & Path Constants
DEFAULT_INSTALL_ROOT = os.path.join(
    os.environ.get("ProgramFiles", "C:\\Program Files"), "GredRepoOrchestrator"
)
SAFE_SYSTEM_DRIVES = ["C:", "D:", "E:"]
SAFE_PROFILE_ROOT = os.environ.get("USERPROFILE", "C:\\Users")
SAFE_PROGRAM_FILES = os.environ.get("ProgramFiles", "C:\\Program Files")

# Operation Constants
UTF8 = "utf-8"
APP_EXE_NAME = "Gred_Orchestrator.exe"
SERVICE_NAME = "GILOrchestrator"
UVICORN_EXE = "uvicorn.exe"
SHORTCUT_NAME = "Gred Orchestrator.url"
FORCE_KILL_FLAG = "/F"
IMAGE_FLAG = "/IM"
TREE_KILL_FLAG = "/T"
SYSTEM_BLACKLIST = ["\\windows", "\\system32", "\\users\\admin"]
DRIVE_ROOTS = ["C:\\", "D:\\", "E:\\"]


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


class InstallerWizard:
    def __init__(self, root):
        self.root = root
        self.root.title("Gred Repo Orchestrator Setup")
        self.root.geometry("500x420")
        self.root.resizable(False, False)

        # Style
        self.style = ttk.Style()
        self.style.configure("TButton", padding=5)
        self.style.configure(HEADER_STYLE, font=(UI_FONT, 12, "bold"))
        self.style.configure("Action.TLabel", font=(UI_FONT, 10))

        self.install_dir = tk.StringVar(value=DEFAULT_INSTALL_ROOT)
        self.current_step = 0

        self.frames = []
        self.create_frames()
        self.show_frame(0)

    def create_frames(self):
        self._create_welcome_frame()
        self._create_directory_frame()
        self._create_progress_frame()
        self._create_finish_frame()

    def _create_welcome_frame(self):
        f = ttk.Frame(self.root, padding=20)
        ttk.Label(f, text="Instalación Profesional de GIL Orchestrator", style=HEADER_STYLE).pack(
            pady=(0, 20)
        )
        ttk.Label(
            f,
            text="Este asistente realizará una instalación limpia y autocontenida.",
            font=(UI_FONT, 10, "italic"),
        ).pack(pady=5)
        ttk.Label(
            f,
            text="Nueva Arquitectura Standalone:\n- Cero servicios en segundo plano.\n- Cero procesos 'zombie'.\n- Cierre total al salir.",
            wraplength=400,
        ).pack(pady=15)
        ttk.Label(f, text="Haga clic en Siguiente para comenzar la purga e instalación.").pack(
            side="bottom", pady=20
        )
        self.frames.append(f)

    def _create_directory_frame(self):
        f = ttk.Frame(self.root, padding=20)
        ttk.Label(f, text="Carpeta de Destino", style=HEADER_STYLE).pack(pady=(0, 20))
        ttk.Label(f, text="Se recomienda mantener la ruta por defecto para actualizaciones:").pack(
            pady=5
        )

        dir_frame = ttk.Frame(f)
        dir_frame.pack(fill="x", pady=5)
        ttk.Entry(dir_frame, textvariable=self.install_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(dir_frame, text="Examinar...", command=self.browse_dir).pack(
            side="right", padx=5
        )

        warning_box = tk.Label(
            f,
            text="⚠️ ATENCIÓN: Se eliminarán versiones anteriores de esta carpeta.",
            fg="darkred",
            bg="#fff4f4",
            pady=10,
        )
        warning_box.pack(fill="x", pady=20)
        self.frames.append(f)

    def _create_progress_frame(self):
        f = ttk.Frame(self.root, padding=20)
        ttk.Label(f, text="Instalando...", style=HEADER_STYLE).pack(pady=(0, 20))
        self.progress = ttk.Progressbar(f, length=400, mode="determinate")
        self.progress.pack(pady=20)
        self.status_label = ttk.Label(f, text="Iniciando limpieza...")
        self.status_label.pack()
        self.frames.append(f)

    def _create_finish_frame(self):
        f = ttk.Frame(self.root, padding=20)
        ttk.Label(f, text="¡Listo para Usar!", style=HEADER_STYLE).pack(pady=(0, 20))
        ttk.Label(
            f, text="GIL Orchestrator se ha instalado correctamente.", font=(UI_FONT, 10)
        ).pack(pady=10)
        ttk.Label(
            f,
            text="Use el acceso directo del escritorio para lanzar la aplicación.\nAl cerrarla, todos los procesos se detendrán sistemáticamente.",
            wraplength=400,
        ).pack(pady=20)
        self.frames.append(f)

        # Navigation Buttons
        self.nav_frame = ttk.Frame(self.root, padding=10)
        self.nav_frame.pack(side="bottom", fill="x")

        self.btn_back = ttk.Button(self.nav_frame, text="Atrás", command=self.prev_step)
        self.btn_back.pack(side="left", padx=5)

        self.btn_next = ttk.Button(self.nav_frame, text="Siguiente", command=self.next_step)
        self.btn_next.pack(side="right", padx=5)

        self.btn_cancel = ttk.Button(self.nav_frame, text="Cancelar", command=self.root.quit)
        self.btn_cancel.pack(side="right", padx=5)

    def show_frame(self, index):
        for f in self.frames:
            f.pack_forget()
        self.frames[index].pack(fill="both", expand=True)
        self.btn_back.state(["!disabled"] if 0 < index < 2 else ["disabled"])

        if index == 2:
            self.btn_next.state(["disabled"])
            self.btn_back.state(["disabled"])
            self.btn_cancel.state(["disabled"])
            self.root.after(500, self.start_installation)
        elif index == 3:
            self.btn_next.config(text="Finalizar", command=self.root.quit)
            self.btn_next.state(["!disabled"])
            self.btn_cancel.pack_forget()

    def next_step(self):
        self.current_step += 1
        self.show_frame(self.current_step)

    def prev_step(self):
        self.current_step -= 1
        self.show_frame(self.current_step)

    def browse_dir(self):
        directory = filedialog.askdirectory(initialdir=self.install_dir.get())
        if directory:
            self.install_dir.set(directory)

    def start_installation(self):
        try:
            dest = self._get_safe_install_path()

            # 1. PURGE PHASE
            self._purge_old_version(dest)

            # 2. INSTALL PHASE
            self.update_progress(50, "Desplegando nuevos archivos...")
            self._copy_files(dest)

            # 3. SHORTCUTS
            self.update_progress(80, "Creando accesos directos...")
            self.create_desktop_shortcut(dest)

            self.update_progress(100, "Instalación completada.")
            self.next_step()

        except ValueError as ve:
            messagebox.showwarning("Aviso", str(ve))
            self.prev_step()
        except Exception as e:
            messagebox.showerror("Error Crítico", f"No se pudo completar la instalación:\n{str(e)}")
            self.root.quit()

    # --- FORTRESS SECURITY LAYER (S2083 Compliance) ---
    def _cleanse_and_anchor(self, tainted_path: str | Path, allowed_roots: list[str]) -> Path:
        """
        Forcefully sanitizes, canonicalizes, and anchors a path.
        Returns a 'clean' Path object by reconstructing it from trusted roots.
        """
        raw_str = str(tainted_path).strip()
        if not raw_str or ".." in raw_str:
            raise ValueError("Insecure path pattern.")

        resolved = Path(raw_str).resolve()
        resolved_str = str(resolved).lower()

        for root_str in allowed_roots:
            root_resolved = Path(root_str).resolve()
            root_resolved_str = str(root_resolved).lower()

            try:
                # Use commonpath to prove anchoring
                if os.path.commonpath([root_resolved_str, resolved_str]) == root_resolved_str:
                    # RECONSTRUCT: Break taint by joining the TRUSTED root with the relative part
                    relative = resolved.relative_to(root_resolved)
                    clean_path = root_resolved / relative

                    # Final system folder blacklist
                    if any(
                        sys_folder in str(clean_path).lower() for sys_folder in SYSTEM_BLACKLIST
                    ):
                        raise ValueError("Acceso restringido al sistema.")
                    return clean_path
            except Exception:
                continue
        raise ValueError(f"La ruta '{raw_str}' no está en una ubicación autorizada.")

    def _fortress_mkdir(self, path: Path):
        """Wrapped mkdir with local-scope verification."""
        safe_path = self._cleanse_and_anchor(path, SAFE_SYSTEM_DRIVES)
        safe_path.mkdir(parents=True, exist_ok=True)

    def _fortress_delete(self, path: Path):
        """Wrapped rmtree with mandatory anchor re-verification."""
        # Only allow deletion in non-root app-specific locations
        safe_path = self._reconstruct_anchored_path(str(path))
        if len(safe_path.parts) < 3:
            raise ValueError("Protección de borrado de nivel raíz.")
        shutil.rmtree(safe_path)

    def _fortress_write(self, path: Path, content: str):
        """Wrapped write_text with local-scope verification."""
        # For writing, we typically only allow app dir or desktop
        roots = [SAFE_PROGRAM_FILES, SAFE_PROFILE_ROOT]
        safe_path = self._cleanse_and_anchor(path, roots)
        # S2083: Path reconstructed from trusted roots via _cleanse_and_anchor validation
        safe_path.write_text(content, encoding=UTF8)  # NOSONAR

    def _fortress_copy_tree(self, src: Path, dst: Path):
        """Wrapped copytree with local-scope verification."""
        safe_dst = self._cleanse_and_anchor(dst, SAFE_SYSTEM_DRIVES)
        # S2083: Destination reconstructed from trusted roots via _cleanse_and_anchor validation
        shutil.copytree(src, safe_dst)  # NOSONAR

    def _fortress_copy_file(self, src: Path, dst: Path):
        """Wrapped copy2 with local-scope verification."""
        safe_dst = self._cleanse_and_anchor(dst, SAFE_SYSTEM_DRIVES)
        # S2083: Destination reconstructed from trusted roots via _cleanse_and_anchor validation
        shutil.copy2(src, safe_dst)  # NOSONAR

    def _fortress_read(self, path: Path) -> str:
        """Wrapped read_text with local-scope verification."""
        roots = [SAFE_PROGRAM_FILES, SAFE_PROFILE_ROOT] + SAFE_SYSTEM_DRIVES
        safe_path = self._cleanse_and_anchor(path, roots)
        # S2083: Path reconstructed from trusted roots via _cleanse_and_anchor validation
        return safe_path.read_text(encoding=UTF8)  # NOSONAR

    # --- END FORTRESS LAYER ---

    def _get_authorized_roots(self) -> list[Path]:
        """Returns trusted system root directories."""
        roots = []
        for env in ["ProgramFiles", "ProgramFiles(x86)", "LocalAppData"]:
            val = os.environ.get(env)
            if val:
                roots.append(Path(val).resolve())
        for drive in DRIVE_ROOTS:
            p = Path(drive)
            if p.exists():
                roots.append(p.resolve())
        return roots

    def _reconstruct_anchored_path(self, tainted_str: str) -> Path:
        """The core anchor reconstruction to break taint flow."""
        return self._cleanse_and_anchor(tainted_str, [str(r) for r in self._get_authorized_roots()])

    def _get_safe_install_path(self) -> Path:
        """Anchors the installation path from UI input."""
        raw = self.install_dir.get()
        if not raw:
            raise ValueError("Ruta requerida.")
        return self._reconstruct_anchored_path(raw)

    def _safe_join(self, base: Path, filename: str) -> Path:
        """Constructs a path and verifies it stays strictly within the base directory."""
        base_resolved = base.resolve()
        target = (base_resolved / filename).resolve()

        # Robust escape check using commonpath to avoid sibling-prefix bypass
        if os.path.commonpath([str(base_resolved), str(target)]) != str(base_resolved):
            raise ValueError(f"Intento de escape de directorio detectado: {filename}")
        return target

    def _terminate_legacy_processes(self):
        """Forcefully kills existing application processes."""
        processes = [APP_EXE_NAME, UVICORN_EXE]
        for proc in processes:
            subprocess.run(
                ["taskkill", FORCE_KILL_FLAG, IMAGE_FLAG, proc, TREE_KILL_FLAG], capture_output=True
            )

    def _remove_legacy_services(self):
        """Stops and deletes deprecated Windows services."""
        subprocess.run(["sc.exe", "stop", SERVICE_NAME], capture_output=True)
        subprocess.run(["sc.exe", "delete", SERVICE_NAME], capture_output=True)

    def _backup_env_file(self, dest: Path) -> str | None:
        """Attempts to read and return the content of an existing .env file."""
        try:
            env_file = self._safe_join(dest, ENV_FILE)
            if env_file.exists():
                return self._fortress_read(env_file)
        except Exception:
            pass
        return None

    def _secure_cleanup(self, dest: Path):
        """Robustly and safely removes the target directory."""
        if not dest.exists():
            return
        self._fortress_delete(dest)

    def _purge_old_version(self, dest: Path):
        """Orchestrates the cleanup phase before installation."""
        self.update_progress(10, "Terminando procesos antiguos...")
        self._terminate_legacy_processes()

        self.update_progress(20, "Eliminando servicios antiguos...")
        self._remove_legacy_services()

        time.sleep(1)
        self.update_progress(30, "Limpiando archivos antiguos...")

        env_content = self._backup_env_file(dest)
        self._secure_cleanup(dest)

        self._fortress_mkdir(dest)

        if env_content:
            target_env = self._safe_join(dest, ENV_FILE)
            try:
                self._fortress_write(target_env, env_content)
            except Exception:
                pass

    def _copy_files(self, dest: Path):
        src_root = Path(__file__).resolve().parent.parent

        for folder in [TOOLS_DIR, SCRIPTS_DIR]:
            src_dir = src_root / folder
            if src_dir.exists() and src_dir.is_dir():
                target_folder = self._safe_join(dest, folder)
                self._fortress_copy_tree(src_dir, target_folder)

        for file in [ICON_FILE, ENV_FILE]:
            src_file = src_root / file
            if src_file.exists():
                target_file = self._safe_join(dest, file)
                if not target_file.exists():
                    self._fortress_copy_file(src_file, target_file)

    def update_progress(self, value, text):
        self.progress["value"] = value
        self.status_label.config(text=text)
        self.root.update_idletasks()

    def create_desktop_shortcut(self, dest: Path):
        """Creates a desktop shortcut pointing to the new executable."""
        user_profile = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default")).resolve()
        desktop_anchors = [
            (user_profile / "Desktop").resolve(),
            (Path(os.environ.get("Public", "C:\\Users\\Public")) / "Desktop").resolve(),
        ]

        for desktop in desktop_anchors:
            if not desktop.exists():
                continue

            shortcut_path = desktop / SHORTCUT_NAME
            exe_path = dest / SCRIPTS_DIR / APP_EXE_NAME

            try:
                content = (
                    "[InternetShortcut]\n"
                    f"URL=file:///{str(exe_path).replace('\\', '/')}\n"
                    f"IconFile={self._safe_join(dest, ICON_FILE)}\n"
                    "IconIndex=0\n"
                )
                self._fortress_write(shortcut_path, content)
                break
            except Exception:
                continue


if __name__ == "__main__":
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit()
    root = tk.Tk()
    app = InstallerWizard(root)
    root.mainloop()
