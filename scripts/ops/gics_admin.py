#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

# Buscamos la ruta al CLI compilado de GICS
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GICS_CLI_JS = REPO_ROOT / "vendor" / "gics" / "dist" / "src" / "cli" / "index.js"

def _run_gics_cmd(args):
    """Ejecuta un comando en el CLI nativo de GICS"""
    if not GICS_CLI_JS.exists():
        print(f"Error: No se encontro el CLI de GICS en {GICS_CLI_JS}")
        print("Asegurate de que vendor/gics haya sido compilado ('npm run build').")
        sys.exit(1)
        
    cmd = ["node", str(GICS_CLI_JS)] + args
    print(f"[{' '.join(cmd)}]")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error ejecutando GICS CLI: codigo {e.returncode}")
        sys.exit(e.returncode)

def main():
    parser = argparse.ArgumentParser(description="GIMO GICS Admin - Scripts en caliente para mantenimiento y rendimiento.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. FLUSH
    subparsers.add_parser("flush", help="Forzar el volcado de la capa HOT (MemTable) a disco WARM.")
    
    # 2. COMPACT
    subparsers.add_parser("compact", help="Compactar segmentos WARM para mejorar rendimiento de lectura.")
    
    # 3. ROTATE
    subparsers.add_parser("rotate", help="Rotar datos WARM antiguos hacia la capa COLD (opcionalmente cifrada).")
    
    # 4. INFERENCE FLUSH
    subparsers.add_parser("flush-inference", help="Forzar el volcado de todos los buffers del Motor de Inferencia.")
    
    # 5. STATUS
    subparsers.add_parser("status", help="Obtener el estado general del demonio GICS en formato JSON.")
    
    # 6. INFERENCE HEALTH
    subparsers.add_parser("infer-health", help="Ver estado y metricas del Motor de Inferencia de GICS.")

    args = parser.parse_args()

    if args.command == "flush":
        print("Iniciando volcado de memoria a disco (HOT -> WARM)...")
        _run_gics_cmd(["daemon", "flush"])
        
    elif args.command == "compact":
        print("Iniciando compactacion de segmentos en la capa WARM...")
        _run_gics_cmd(["daemon", "compact"])
        
    elif args.command == "rotate":
        print("Iniciando rotacion de datos (WARM -> COLD)...")
        _run_gics_cmd(["daemon", "rotate"])
        
    elif args.command == "flush-inference":
        print("Volcando estado del runtime de inferencia...")
        _run_gics_cmd(["inference", "flush"])

    elif args.command == "status":
        _run_gics_cmd(["daemon", "status", "--json"])

    elif args.command == "infer-health":
        _run_gics_cmd(["inference", "health"])

if __name__ == "__main__":
    main()
