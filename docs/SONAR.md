# Sonar (SonarCloud) Continuous Analysis

Este repositorio está configurado para ejecutar análisis continuo de código con SonarCloud en cada `push` y `pull_request` mediante GitHub Actions.

> **Nota:** Si el repositorio es privado y no se usa SonarCloud, puedes sustituir el workflow para SonarQube Server. En ese caso necesitarás `SONAR_HOST_URL` además de `SONAR_TOKEN`.

## 1) Crear proyecto en SonarCloud
1. Entra a https://sonarcloud.io y crea un proyecto nuevo.
2. Selecciona la organización (Organization) y conecta el repositorio de GitHub.
3. Copia el `Project Key` y el `Organization Key`.

## 2) Actualizar `sonar-project.properties`
Edita el archivo en la raíz del repo y reemplaza los placeholders:
- `sonar.projectKey=CHANGE_ME_PROJECT_KEY`
- `sonar.organization=CHANGE_ME_ORG`

## 3) GitHub Secrets requeridos
En el repositorio de GitHub, ve a **Settings → Secrets and variables → Actions** y crea:
- `SONAR_TOKEN`: Token de acceso de SonarCloud con permisos para analizar el proyecto.
- *(Solo SonarQube self-hosted)* `SONAR_HOST_URL`: URL del servidor, por ejemplo `https://sonarqube.mi-dominio.com`.

## 4) Verificar el workflow
1. Abre una Pull Request o haz un `push` a una rama.
2. Ve a **Actions → Sonar** y confirma que el job termina en verde.
3. En SonarCloud, abre el proyecto y valida que el análisis aparece en **Activity**.

## Troubleshooting
- **Project Key incorrecto**: confirma que `sonar.projectKey` coincide exactamente con el Project Key de SonarCloud.
- **Falta de token**: asegura que `SONAR_TOKEN` existe y tiene permisos para el proyecto.
- **fetch-depth insuficiente**: el checkout debe usar `fetch-depth: 0` para que el análisis de PR funcione correctamente.
- **Exclusions mal puestas**: revisa `sonar.exclusions` si faltan archivos esperados o se analizan artefactos generados.
- **Cobertura no encontrada**: confirma que `pytest --cov` genere `coverage.xml` en la raíz antes del scan.
