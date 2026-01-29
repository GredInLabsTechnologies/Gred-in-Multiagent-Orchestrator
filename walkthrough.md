# walkthrough.md — Technical Debt Narrative

## 1. ¿Dónde duele más?
El dolor principal reside en la **falta de una frontera clara entre la interfaz y la lógica**. Actualmente, el orquestador es un "monolito de conveniencia":
- El backend (`main.py`) intenta ser servidor de archivos, gestor de git y host de interfaz al mismo tiempo.
- La configuración está "semi-hardcodeada", lo que hará que el despliegue en el puente de Actions sea frágil ante cambios de rutas en el entorno de GitHub.

## 2. Deuda Sistémica
La deuda más peligrosa es la de **Reproducibilidad**. Sin un archivo de dependencias estándar (`requirements.txt`), el proyecto depende del estado accidental de la máquina del desarrollador. Esto es una "mina" para cualquier sistema de CI/CD automatizado como el puente de Actions.

## 3. Bloqueadores del "Actions Bridge"
Para que el puente Actions funcione de forma robusta, se DEBEN resolver estos puntos:
- **Headless mode**: Eliminar llamadas a `explorer.exe` y `Tkinter` en rutas de ejecución lógica.
- **Dependency Manifest**: Crear el `requirements.txt` para que el runner de Actions pueda instalar el entorno.
- **Service Layer**: El puente necesitará llamar a funciones de Git/FS sin pasar por la capa HTTP de FastAPI en algunos casos. Actualmente, esa lógica está atrapada dentro de las rutas de la API.

## 4. Estrategia de Eliminación RECOMENDADA

### Fase 1: Limpieza de Superficie (Quick Wins)
- Borrar el dashboard duplicado.
- Crear manifiesto de dependencias.
- Unificar el lenguaje (comentarios/logs) a un solo estándar (preferiblemente inglés para alinearse con los nombres de variables, o español consistente).

### Fase 2: Desacoplamiento (Para Actions Bridge)
- Extraer lógica de `main.py` a servicios puros.
- Implementar una CLI mínima para el orquestador que no dependa de la GUI de Tkinter.

### Fase 3: Robustez Profesional
- Añadir Unit Tests a la lógica de `security.py`. Es el corazón del sistema y cualquier error ahí compromete todo el repositorio.
