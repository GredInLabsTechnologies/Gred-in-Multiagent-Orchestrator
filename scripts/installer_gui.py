import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import ctypes
import time

UI_FONT = "Segoe UI"
HEADER_STYLE = "Header.TLabel"
ICON_FILE = "orchestrator_icon.ico"
ENV_FILE = ".env"
SCRIPTS_DIR = "scripts"
TOOLS_DIR = "tools"

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
        
        self.install_dir = tk.StringVar(value=os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "GredRepoOrchestrator"))
        self.current_step = 0
        
        self.frames = []
        self.create_frames()
        self.show_frame(0)

    def create_frames(self):
        # Frame 0: Welcome
        f0 = ttk.Frame(self.root, padding=20)
        ttk.Label(f0, text="Instalación Profesional de GIL Orchestrator", style=HEADER_STYLE).pack(pady=(0, 20))
        ttk.Label(f0, text="Este asistente realizará una instalación limpia y autocontenida.", font=(UI_FONT, 10, "italic")).pack(pady=5)
        ttk.Label(f0, text="Nueva Arquitectura Standalone:\n- Cero servicios en segundo plano.\n- Cero procesos 'zombie'.\n- Cierre total al salir.", wraplength=400).pack(pady=15)
        ttk.Label(f0, text="Haga clic en Siguiente para comenzar la purga e instalación.").pack(side="bottom", pady=20)
        self.frames.append(f0)

        # Frame 1: Directory Selection
        f1 = ttk.Frame(self.root, padding=20)
        ttk.Label(f1, text="Carpeta de Destino", style=HEADER_STYLE).pack(pady=(0, 20))
        ttk.Label(f1, text="Se recomienda mantener la ruta por defecto para actualizaciones:").pack(pady=5)
        
        dir_frame = ttk.Frame(f1)
        dir_frame.pack(fill="x", pady=5)
        ttk.Entry(dir_frame, textvariable=self.install_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(dir_frame, text="Examinar...", command=self.browse_dir).pack(side="right", padx=5)
        
        warning_box = tk.Label(f1, text="⚠️ ATENCIÓN: Se eliminarán versiones anteriores de esta carpeta.", fg="darkred", bg="#fff4f4", pady=10)
        warning_box.pack(fill="x", pady=20)
        self.frames.append(f1)

        # Frame 2: Progress
        f2 = ttk.Frame(self.root, padding=20)
        ttk.Label(f2, text="Instalando...", style=HEADER_STYLE).pack(pady=(0, 20))
        self.progress = ttk.Progressbar(f2, length=400, mode='determinate')
        self.progress.pack(pady=20)
        self.status_label = ttk.Label(f2, text="Iniciando limpieza...")
        self.status_label.pack()
        self.frames.append(f2)

        # Frame 3: Finish
        f3 = ttk.Frame(self.root, padding=20)
        ttk.Label(f3, text="¡Listo para Usar!", style=HEADER_STYLE).pack(pady=(0, 20))
        ttk.Label(f3, text="GIL Orchestrator se ha instalado correctamente.", font=(UI_FONT, 10)).pack(pady=10)
        ttk.Label(f3, text="Use el acceso directo del escritorio para lanzar la aplicación.\nAl cerrarla, todos los procesos se detendrán sistemáticamente.", wraplength=400).pack(pady=20)
        self.frames.append(f3)

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

    def _get_safe_install_path(self) -> Path:
        """
        Sanitizes and validates the installation directory to prevent Path Injection (S2083).
        """
        raw_path = self.install_dir.get().strip()
        
        # 1. Block basic traversal attempts before ANY processing
        if not raw_path or ".." in raw_path:
            raise ValueError("Ruta de instalación inválida o insegura.")

        # 2. Canonicalize using absolute path
        dest = Path(raw_path).resolve()
        abs_str = str(dest).lower()

        # 3. Strict Blacklist (starts_with check to cover all subfolders)
        forbidden = [
            "c:\\windows", 
            "c:\\users", 
            "c:\\programdata", 
            "c:\\$recycle.bin",
            "c:\\perflogs"
        ]
        for root in forbidden:
            if abs_str.startswith(root):
                raise ValueError(f"Directorio restringido por el sistema: {root}")

        # 4. Structural validation: Ensure it's not a drive root (e.g., C:\)
        if len(dest.parts) < 2:
            raise ValueError("Debe especificar una subcarpeta de instalación (ej: C:\\Program Files\\App).")

        return dest

    def _safe_join(self, base: Path, filename: str) -> Path:
        """Constructs a path and verifies it stays within the base directory."""
        target = (base / filename).resolve()
        if not str(target).startswith(str(base)):
            raise ValueError("Intento de escape de directorio detectado.")
        return target

    def _purge_old_version(self, dest: Path):
        self.update_progress(10, "Terminando procesos antiguos...")
        subprocess.run(["taskkill", "/F", "/IM", "Gred_Orchestrator.exe", "/T"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "uvicorn.exe", "/T"], capture_output=True)
        
        self.update_progress(20, "Eliminando servicios antiguos...")
        subprocess.run(["sc.exe", "stop", "GILOrchestrator"], capture_output=True)
        subprocess.run(["sc.exe", "delete", "GILOrchestrator"], capture_output=True)
        
        time.sleep(1)
        self.update_progress(30, "Limpiando archivos antiguos...")
        
        # Safe handling of existing artifacts
        env_content = None
        try:
            env_file = self._safe_join(dest, ENV_FILE)
            if env_file.exists():
                env_content = env_file.read_text(encoding="utf-8")
        except Exception: 
            pass
        
        if dest.exists() and dest.is_dir():
            for _ in range(3):
                try:
                    shutil.rmtree(dest)
                    break
                except Exception:
                    time.sleep(1)
        
        dest.mkdir(parents=True, exist_ok=True)
        if env_content:
            try:
                self._safe_join(dest, ENV_FILE).write_text(env_content, encoding="utf-8")
            except Exception: pass

    def _copy_files(self, dest: Path):
        src_root = Path(__file__).parent.parent
        
        for folder in [TOOLS_DIR, SCRIPTS_DIR]:
            src_dir = src_root / folder
            if src_dir.exists() and src_dir.is_dir():
                shutil.copytree(src_dir, self._safe_join(dest, folder))
        
        icon_src = src_root / ICON_FILE
        if icon_src.exists():
            shutil.copy2(icon_src, self._safe_join(dest, ICON_FILE))
            
        # Fallback for .env if not restored from previous install
        env_src = src_root / ENV_FILE
        target_env = self._safe_join(dest, ENV_FILE)
        if not target_env.exists() and env_src.exists():
            shutil.copy2(env_src, target_env)

    def update_progress(self, value, text):
        self.progress["value"] = value
        self.status_label.config(text=text)
        self.root.update_idletasks()

    def create_desktop_shortcut(self, dest):
        desktop = Path(os.path.join(os.environ["USERPROFILE"], "Desktop"))
        # We will point the shortcut TO THE NEW STANDALONE EXE
        shortcut_path = desktop / "Gred Orchestrator.url"
        exe_path = dest / SCRIPTS_DIR / "Gred_Orchestrator.exe" # This will be the result of PyInstaller
        
        try:
            with open(shortcut_path, "w") as f:
                f.write("[InternetShortcut]\n")
                # Since it's a local EXE, we can't easily use .url for non-browser things without caveats
                # but for simplicity in this script we'll point it to the local app's URL 
                # OR we'll use a better method if available. 
                # Standard approach for PyInstaller is to let the user find the EXE, 
                # but we want it 'professional'.
                f.write(f"URL=file:///{str(exe_path).replace('\\', '/')}\n")
                f.write(f"IconFile={self._safe_join(dest, ICON_FILE)}\n")
                f.write("IconIndex=0\n")
        except Exception:
            pass

if __name__ == "__main__":
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()
    root = tk.Tk()
    app = InstallerWizard(root)
    root.mainloop()
