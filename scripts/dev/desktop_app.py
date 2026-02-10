import ctypes
import os
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

import uvicorn

UI_FONT = "Segoe UI"

# Fix pathing for bundled execution
# scripts/dev/*.py -> repo root
BASE_DIR = Path(__file__).parent.parent.parent
sys.path.append(str(BASE_DIR))


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


class OrchestratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Gred Repo Orchestrator")
        self.root.geometry("400x250")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # UI Elements
        self.label = tk.Label(root, text="GIL Orchestrator", font=(UI_FONT, 16, "bold"))
        self.label.pack(pady=20)

        self.status_label = tk.Label(root, text="Iniciando servidor...", fg="blue")
        self.status_label.pack(pady=10)

        self.btn_open = tk.Button(
            root, text="Abrir Dashboard", command=self.open_browser, state="disabled"
        )
        self.btn_open.pack(pady=10)

        self.btn_stop = tk.Button(
            root, text="Detener y Salir", command=self.on_closing, bg="#f44336", fg="white"
        )
        self.btn_stop.pack(pady=10)

        # Server Thread
        self.server_started = False
        self.should_exit = False
        self.server_thread = threading.Thread(target=self.run_server, daemon=True)
        self.server_thread.start()

        # Check server status periodically
        self.root.after(1000, self.check_server)

    def run_server(self):
        config = uvicorn.Config(
            "tools.gimo_server.main:app",
            host="127.0.0.1",
            port=9325,
            log_level="info",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.server.run()

    def check_server(self):
        if hasattr(self, "server") and self.server.started:
            self.status_label.config(text="● Servidor en ejecución (Puerto 9325)", fg="green")
            self.btn_open.config(state="normal")
            if not self.server_started:
                self.server_started = True
                self.open_browser()

        if not self.should_exit:
            self.root.after(1000, self.check_server)

    def open_browser(self):
        webbrowser.open("http://localhost:9325")

    def on_closing(self):
        if messagebox.askokcancel("Salir", "¿Deseas cerrar el Orquestador y apagar el servidor?"):
            self.should_exit = True
            if hasattr(self, "server"):
                self.server.should_exit = True
            self.root.destroy()
            sys.exit(0)


def run_headless():
    print("● Iniciando Orquestador en modo HEADLESS (Sin interfaz)")
    config = uvicorn.Config(
        "tools.gimo_server.main:app",
        host="127.0.0.1",
        port=9325,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    # Ensure it's running from the right directory
    os.chdir(str(BASE_DIR))

    if os.environ.get("ORCH_HEADLESS") == "true":
        run_headless()
        sys.exit(0)

    root = tk.Tk()
    # Set icon if exists
    icon_path = BASE_DIR / "orchestrator_icon.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    app = OrchestratorApp(root)
    root.mainloop()
