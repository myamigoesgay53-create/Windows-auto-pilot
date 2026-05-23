# Windows AI Autopilot (Python + OpenAI)

App de escritorio para Windows que recibe una tarea en texto y usa OpenAI para ejecutar acciones reales en el PC:

- control de raton y teclado mediante Computer Use
- navegacion web
- herramientas locales para leer/buscar/escribir archivos

## Importante

- Usa esta app solo en un entorno que controles.
- Empieza con tareas de bajo riesgo.
- La automatizacion de interfaz puede cometer errores.
- En **modo seguro** (activado por defecto) se bloquea escritura fuera de la carpeta del proyecto y se frena cuando la API solicita safety checks.

## Requisitos

- Windows 10/11
- Python 3.10 o superior (recomendado 3.10-3.13; 3.14 puede requerir dependencias aun en actualizacion)

## Instalacion

1. Abre PowerShell en esta carpeta.
2. Crea y activa entorno virtual:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

3. Instala dependencias:

```powershell
pip install -r requirements.txt
```

4. Configura la API key (opcional por `.env`):

```powershell
Copy-Item .env.example .env
```

Luego edita `.env` y pega tu clave en `OPENAI_API_KEY`.

## Ejecutar

```powershell
python main.py
```

O con doble clic/terminal:

```powershell
run_app.bat
```

## Uso rapido

1. Pon tu API key (o usa `.env`).
2. Escribe la tarea en texto.
3. Pulsa **Iniciar Autopiloto**.
4. Si necesitas parar, usa **Parar**.
5. Parada de emergencia adicional: mueve el raton a la esquina superior izquierda (FailSafe de PyAutoGUI).

Si venias de una instalacion anterior, actualiza dependencias:

```powershell
pip install -U -r requirements.txt
```

## Ejemplos de tarea

- "Abre el navegador, busca tres opciones de coworking en Madrid centro, compara precio y guarda resumen en `resultado.txt`."
- "Busca en mi carpeta `Documentos` archivos que contengan `factura` en el nombre y listalos."

## Estructura

- `main.py`: interfaz y motor del agente.
- `requirements.txt`: dependencias.
- `.env.example`: plantilla de variables de entorno.
