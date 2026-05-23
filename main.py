import base64
import io
import json
import os
import queue
import threading
import time
import traceback
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pyautogui
import tkinter as tk
from dotenv import load_dotenv
from openai import OpenAI
from tkinter import messagebox, scrolledtext, ttk

try:
    import mss
    import mss.tools as mss_tools
except Exception:
    mss = None
    mss_tools = None


WORKSPACE_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "gpt-5.5"

SYSTEM_INSTRUCTIONS = """Eres un piloto automatico para Windows.
Tu objetivo es completar la tarea indicada por el usuario.

Reglas:
1) Para acciones de interfaz usa la herramienta "computer".
2) Para archivos locales usa las funciones disponibles.
3) Resume brevemente lo que hiciste y el resultado final cuando termines.
4) No hagas acciones destructivas (borrar masivo, formatear, desinstalar, apagar equipo, editar registro) salvo que el usuario lo pida de forma explicita y directa.
5) Si algo requiere credenciales, compras, pagos o datos sensibles, pide confirmacion textual antes de continuar.
6) Prioriza pasos reversibles y seguros.
"""


class StopRequested(Exception):
    pass


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True)
    if hasattr(item, "__dict__"):
        data = {}
        for key, value in item.__dict__.items():
            if value is not None:
                data[key] = value
        return data
    return {}


def _extract_output_text(response: Any) -> str:
    text_parts: list[str] = []
    output_items = _get(response, "output", []) or []
    for item in output_items:
        if _get(item, "type") != "message":
            continue
        for content in _get(item, "content", []) or []:
            if _get(content, "type") == "output_text":
                text = _get(content, "text")
                if text:
                    text_parts.append(text)
    return "\n".join(text_parts).strip()


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _normalize_key(key: str) -> str:
    k = (key or "").strip().lower()
    mapping = {
        "control": "ctrl",
        "ctl": "ctrl",
        "command": "win",
        "cmd": "win",
        "meta": "win",
        "super": "win",
        "option": "alt",
        "return": "enter",
        "escape": "esc",
        "spacebar": "space",
        "pageup": "pgup",
        "pagedown": "pgdn",
        "arrowup": "up",
        "arrowdown": "down",
        "arrowleft": "left",
        "arrowright": "right",
        "delete": "del",
    }
    return mapping.get(k, k)


class DesktopController:
    def __init__(self, logger: Callable[[str], None], stop_event: threading.Event):
        self.log = logger
        self.stop_event = stop_event
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StopRequested("Detenido por el usuario.")

    def _screen_size(self) -> tuple[int, int]:
        size = pyautogui.size()
        return int(size.width), int(size.height)

    def _clamp_point(self, x: Any, y: Any) -> tuple[int, int]:
        width, height = self._screen_size()
        cx = max(0, min(int(x), max(0, width - 1)))
        cy = max(0, min(int(y), max(0, height - 1)))
        return cx, cy

    def capture_screenshot_base64(self) -> str:
        self._check_stop()
        if mss is not None and mss_tools is not None:
            with mss.mss() as sct:
                # monitor[0] captura todos los monitores en una sola imagen.
                shot = sct.grab(sct.monitors[0])
                png_bytes = mss_tools.to_png(shot.rgb, shot.size)
                return base64.b64encode(png_bytes).decode("ascii")

        # Fallback: mantiene compatibilidad con entornos sin mss funcional.
        try:
            screenshot = pyautogui.screenshot()
            buffer = io.BytesIO()
            screenshot.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception as exc:
            raise RuntimeError(
                "No se pudo capturar pantalla. Ejecuta: pip install -U -r requirements.txt "
                "y, si usas Python 3.14, considera Python 3.13 para mayor compatibilidad."
            ) from exc

    def execute_actions(self, actions: list[Any]) -> None:
        for action in actions:
            self._check_stop()
            self.execute_action(_to_dict(action))

    def _press_with_modifiers(self, keys: list[str], callback: Callable[[], None]) -> None:
        normalized = [_normalize_key(k) for k in keys if k]
        pressed: list[str] = []
        try:
            for key in normalized:
                pyautogui.keyDown(key)
                pressed.append(key)
            callback()
        finally:
            for key in reversed(pressed):
                pyautogui.keyUp(key)

    def execute_action(self, action: dict[str, Any]) -> None:
        action_type = action.get("type")
        keys = action.get("keys") or []
        if not isinstance(keys, list):
            keys = []

        if action_type == "click":
            x, y = self._clamp_point(action.get("x", 0), action.get("y", 0))
            button = action.get("button", "left")
            if button == "wheel":
                button = "middle"
            if button not in {"left", "right", "middle"}:
                button = "left"
            self.log(f"Accion: click {button} en ({x}, {y})")
            self._press_with_modifiers(keys, lambda: pyautogui.click(x=x, y=y, button=button))
            return

        if action_type == "double_click":
            x, y = self._clamp_point(action.get("x", 0), action.get("y", 0))
            self.log(f"Accion: doble click en ({x}, {y})")
            self._press_with_modifiers(keys, lambda: pyautogui.doubleClick(x=x, y=y))
            return

        if action_type == "move":
            x, y = self._clamp_point(action.get("x", 0), action.get("y", 0))
            self.log(f"Accion: mover raton a ({x}, {y})")
            self._press_with_modifiers(keys, lambda: pyautogui.moveTo(x=x, y=y, duration=0.1))
            return

        if action_type == "drag":
            path = action.get("path") or []
            if not path:
                return
            points = []
            for node in path:
                node_dict = _to_dict(node)
                points.append(self._clamp_point(node_dict.get("x", 0), node_dict.get("y", 0)))
            self.log(f"Accion: arrastrar por {len(points)} puntos")

            def do_drag() -> None:
                start_x, start_y = points[0]
                pyautogui.moveTo(start_x, start_y, duration=0.1)
                pyautogui.mouseDown()
                for x, y in points[1:]:
                    pyautogui.moveTo(x, y, duration=0.08)
                pyautogui.mouseUp()

            self._press_with_modifiers(keys, do_drag)
            return

        if action_type == "scroll":
            x, y = self._clamp_point(action.get("x", 0), action.get("y", 0))
            scroll_x = int(action.get("scroll_x", 0))
            scroll_y = int(action.get("scroll_y", 0))
            self.log(f"Accion: scroll x={scroll_x}, y={scroll_y} en ({x}, {y})")

            def do_scroll() -> None:
                pyautogui.moveTo(x, y, duration=0.05)
                if scroll_y:
                    pyautogui.scroll(scroll_y)
                if scroll_x and hasattr(pyautogui, "hscroll"):
                    pyautogui.hscroll(scroll_x)

            self._press_with_modifiers(keys, do_scroll)
            return

        if action_type == "keypress":
            raw_keys = action.get("keys") or []
            if not raw_keys:
                return
            hotkey = [_normalize_key(k) for k in raw_keys if k]
            self.log(f"Accion: keypress {' + '.join(hotkey)}")
            if len(hotkey) == 1:
                pyautogui.press(hotkey[0])
            else:
                pyautogui.hotkey(*hotkey)
            return

        if action_type == "type":
            text = str(action.get("text", ""))
            self.log(f"Accion: escribir texto ({len(text)} chars)")
            pyautogui.write(text, interval=0)
            return

        if action_type == "wait":
            self.log("Accion: esperar")
            time.sleep(1.25)
            return

        if action_type == "screenshot":
            self.log("Accion: solicitud de screenshot")
            return

        self.log(f"Accion no soportada: {action_type}")


class LocalTools:
    def __init__(
        self,
        workspace_root: Path,
        safe_mode: bool,
        logger: Callable[[str], None],
    ):
        self.workspace_root = workspace_root.resolve()
        self.safe_mode = safe_mode
        self.log = logger

    def specs(self) -> list[dict[str, Any]]:
        return [
            {"type": "computer"},
            {
                "type": "function",
                "name": "list_directory",
                "description": "Lista archivos y carpetas de una ruta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Ruta absoluta o relativa.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximo de elementos a devolver.",
                            "minimum": 1,
                            "maximum": 500,
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "search_files",
                "description": "Busca archivos/carpetas por nombre dentro de una ruta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "root": {
                            "type": "string",
                            "description": "Ruta base para buscar.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 300,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "read_text_file",
                "description": "Lee contenido de archivo de texto.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_chars": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 120000,
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "write_text_file",
                "description": "Escribe texto en archivo local.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "append": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "open_url",
                "description": "Abre una URL en el navegador por defecto.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "open_path",
                "description": "Abre una carpeta o archivo usando el programa por defecto.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        ]

    def _resolve_path(self, raw_path: str) -> Path:
        path_text = (raw_path or ".").strip()
        candidate = Path(path_text).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.workspace_root / candidate).resolve()

    def _assert_write_allowed(self, path: Path) -> None:
        if self.safe_mode and not _is_relative_to(path, self.workspace_root):
            raise PermissionError(
                f"Modo seguro activo: solo se puede escribir dentro de {self.workspace_root}"
            )

    def _list_directory(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(str(args.get("path", ".")))
        limit = int(args.get("limit", 200))
        if not path.exists():
            raise FileNotFoundError(f"No existe: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"No es carpeta: {path}")

        entries: list[dict[str, Any]] = []
        for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                stat = item.stat()
                entries.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "is_dir": item.is_dir(),
                        "size_bytes": stat.st_size if item.is_file() else None,
                        "modified_epoch": int(stat.st_mtime),
                    }
                )
            except OSError:
                entries.append({"name": item.name, "path": str(item), "error": "Sin acceso"})
            if len(entries) >= limit:
                break
        return {"ok": True, "path": str(path), "entries": entries}

    def _search_files(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip().lower()
        if not query:
            raise ValueError("query vacio")
        root = self._resolve_path(str(args.get("root", ".")))
        limit = int(args.get("limit", 80))
        if not root.exists():
            raise FileNotFoundError(f"No existe: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"No es carpeta: {root}")

        matches: list[dict[str, Any]] = []
        for item in root.rglob("*"):
            if query in item.name.lower():
                matches.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "is_dir": item.is_dir(),
                    }
                )
            if len(matches) >= limit:
                break
        return {"ok": True, "root": str(root), "matches": matches}

    def _read_text_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(str(args.get("path", "")))
        max_chars = int(args.get("max_chars", 12000))
        if not path.exists():
            raise FileNotFoundError(f"No existe: {path}")
        if path.is_dir():
            raise IsADirectoryError(f"Es una carpeta: {path}")

        text = path.read_text(encoding="utf-8", errors="replace")
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True
        return {
            "ok": True,
            "path": str(path),
            "truncated": truncated,
            "content": text,
        }

    def _write_text_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(str(args.get("path", "")))
        content = str(args.get("content", ""))
        append = bool(args.get("append", False))
        self._assert_write_allowed(path)

        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8", errors="replace") as f:
            f.write(content)
        return {
            "ok": True,
            "path": str(path),
            "chars_written": len(content),
            "append": append,
        }

    def _open_url(self, args: dict[str, Any]) -> dict[str, Any]:
        raw_url = str(args.get("url", "")).strip()
        if not raw_url:
            raise ValueError("url vacia")
        if not raw_url.startswith(("http://", "https://", "file://")):
            raw_url = "https://" + raw_url
        webbrowser.open(raw_url)
        return {"ok": True, "url": raw_url}

    def _open_path(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(str(args.get("path", "")))
        if not path.exists():
            raise FileNotFoundError(f"No existe: {path}")

        blocked_suffix = {".exe", ".bat", ".cmd", ".ps1", ".reg", ".msi", ".vbs"}
        if self.safe_mode and path.suffix.lower() in blocked_suffix:
            raise PermissionError("Modo seguro activo: bloqueo de apertura de ejecutables/scripts.")

        os.startfile(str(path))
        return {"ok": True, "path": str(path)}

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.log(f"Herramienta local: {name}")
        router = {
            "list_directory": self._list_directory,
            "search_files": self._search_files,
            "read_text_file": self._read_text_file,
            "write_text_file": self._write_text_file,
            "open_url": self._open_url,
            "open_path": self._open_path,
        }
        if name not in router:
            raise ValueError(f"Funcion no soportada: {name}")
        return router[name](args)


@dataclass
class RunConfig:
    api_key: str
    model: str
    max_turns: int
    safe_mode: bool


class WindowsAutopilotAgent:
    def __init__(self, config: RunConfig, log: Callable[[str], None], stop_event: threading.Event):
        self.config = config
        self.log = log
        self.stop_event = stop_event
        self.client = OpenAI(api_key=config.api_key)
        if not hasattr(self.client, "responses"):
            raise RuntimeError(
                "Tu paquete openai es antiguo y no expone Responses API. Actualiza con: pip install -U openai"
            )
        self.desktop = DesktopController(log, stop_event)
        self.tools = LocalTools(WORKSPACE_ROOT, config.safe_mode, log)

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StopRequested("Detenido por el usuario.")

    def _get_actions_from_computer_call(self, item: Any) -> list[Any]:
        actions = _get(item, "actions")
        if actions:
            if isinstance(actions, list):
                return actions
            try:
                return list(actions)
            except TypeError:
                pass
        single_action = _get(item, "action")
        if single_action:
            return [single_action]
        return []

    def _handle_function_call(self, item: Any) -> dict[str, Any]:
        call_id = _get(item, "call_id")
        name = _get(item, "name")
        raw_args = _get(item, "arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except Exception:
            args = {}

        try:
            result = self.tools.execute(name, args)
            output = json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            output = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        }

    def _handle_computer_call(self, item: Any) -> dict[str, Any]:
        call_id = _get(item, "call_id")
        pending_checks = _get(item, "pending_safety_checks", []) or []

        if pending_checks and self.config.safe_mode:
            details = []
            for check in pending_checks:
                check_dict = _to_dict(check)
                details.append(
                    f"- {check_dict.get('id')} | {check_dict.get('code', 'sin_codigo')} | {check_dict.get('message', '')}"
                )
            joined = "\n".join(details)
            raise PermissionError(
                "La API pidio acknowledge de seguridad y el modo seguro esta activo.\n"
                "Desactiva modo seguro si quieres permitir esta accion.\n"
                f"Checks:\n{joined}"
            )

        actions = self._get_actions_from_computer_call(item)
        self.desktop.execute_actions(actions)
        time.sleep(0.25)
        screenshot_b64 = self.desktop.capture_screenshot_base64()

        output_item: dict[str, Any] = {
            "type": "computer_call_output",
            "call_id": call_id,
            "output": {
                "type": "computer_screenshot",
                "image_url": f"data:image/png;base64,{screenshot_b64}",
            },
        }

        if pending_checks:
            ack = []
            for check in pending_checks:
                check_dict = _to_dict(check)
                entry = {"id": check_dict.get("id")}
                if check_dict.get("code"):
                    entry["code"] = check_dict["code"]
                if check_dict.get("message"):
                    entry["message"] = check_dict["message"]
                ack.append(entry)
            output_item["acknowledged_safety_checks"] = ack

        return output_item

    def run(self, task: str) -> str:
        self._check_stop()
        self.log(f"Modelo: {self.config.model}")
        self.log("Iniciando ejecucion...")

        response = self.client.responses.create(
            model=self.config.model,
            instructions=SYSTEM_INSTRUCTIONS,
            tools=self.tools.specs(),
            input=task,
        )

        final_text = ""
        for turn in range(1, self.config.max_turns + 1):
            self._check_stop()
            self.log(f"Turno {turn}/{self.config.max_turns}")

            output_items = _get(response, "output", []) or []
            tool_outputs: list[dict[str, Any]] = []

            for item in output_items:
                item_type = _get(item, "type")
                if item_type == "computer_call":
                    tool_outputs.append(self._handle_computer_call(item))
                elif item_type == "function_call":
                    tool_outputs.append(self._handle_function_call(item))

            if not tool_outputs:
                final_text = _extract_output_text(response)
                break

            response = self.client.responses.create(
                model=self.config.model,
                tools=self.tools.specs(),
                previous_response_id=_get(response, "id"),
                input=tool_outputs,
            )

        if not final_text:
            final_text = _extract_output_text(response)
        return final_text or "Ejecucion finalizada sin texto de salida."


class AppUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("OpenAI Windows Autopilot (Python)")
        self.root.geometry("980x760")

        self.worker_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.api_key_var = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.max_turns_var = tk.IntVar(value=30)
        self.safe_mode_var = tk.BooleanVar(value=True)
        self.show_key_var = tk.BooleanVar(value=False)

        self._build_layout()
        self.root.after(100, self._drain_ui_queue)

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        top = ttk.LabelFrame(container, text="Configuracion")
        top.pack(fill="x")

        ttk.Label(top, text="OpenAI API Key").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.api_entry = ttk.Entry(top, textvariable=self.api_key_var, width=70, show="*")
        self.api_entry.grid(row=0, column=1, sticky="we", padx=8, pady=6)
        ttk.Checkbutton(
            top,
            text="Mostrar",
            variable=self.show_key_var,
            command=self._toggle_show_key,
        ).grid(row=0, column=2, sticky="w", padx=4, pady=6)

        ttk.Label(top, text="Modelo").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(top, textvariable=self.model_var, width=20).grid(
            row=1, column=1, sticky="w", padx=8, pady=6
        )

        ttk.Label(top, text="Max turnos").grid(row=1, column=1, sticky="e", padx=200, pady=6)
        ttk.Spinbox(top, from_=1, to=200, textvariable=self.max_turns_var, width=8).grid(
            row=1, column=2, sticky="w", padx=8, pady=6
        )

        ttk.Checkbutton(
            top,
            text="Modo seguro (bloquea escrituras fuera de la carpeta del proyecto y solicita freno en safety checks)",
            variable=self.safe_mode_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=6)

        ttk.Label(top, text=f"Carpeta de trabajo: {WORKSPACE_ROOT}").grid(
            row=3, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8)
        )

        top.columnconfigure(1, weight=1)

        task_box = ttk.LabelFrame(container, text="Tarea")
        task_box.pack(fill="both", expand=False, pady=(10, 0))
        self.task_text = scrolledtext.ScrolledText(task_box, height=7, wrap="word")
        self.task_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.task_text.insert(
            "1.0",
            "Ejemplo: abre el navegador, busca restaurantes japoneses cerca de mi, compara 3 opciones y guarda un resumen en resumen.txt.",
        )

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(10, 0))

        self.start_btn = ttk.Button(buttons, text="Iniciar Autopiloto", command=self.start_run)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(buttons, text="Parar", command=self.stop_run, state="disabled")
        self.stop_btn.pack(side="left", padx=8)

        ttk.Button(buttons, text="Limpiar Log", command=self.clear_log).pack(side="left")

        ttk.Label(
            buttons,
            text="Parada de emergencia adicional: mueve el raton a la esquina superior izquierda.",
        ).pack(side="right")

        log_frame = ttk.LabelFrame(container, text="Actividad")
        log_frame.pack(fill="both", expand=True, pady=(10, 0))

        self.log_text = scrolledtext.ScrolledText(log_frame, height=18, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    def _toggle_show_key(self) -> None:
        self.api_entry.configure(show="" if self.show_key_var.get() else "*")

    def _set_running_state(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def queue_log(self, text: str) -> None:
        self.ui_queue.put(("log", text))

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                event, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self.log(str(payload))
            elif event == "done":
                self._set_running_state(False)
                result_text = str(payload).strip()
                if result_text:
                    self.log("Resultado final:")
                    self.log(result_text)
            elif event == "error":
                self._set_running_state(False)
                self.log(f"Error: {payload}")
                messagebox.showerror("Autopiloto", str(payload))

        self.root.after(100, self._drain_ui_queue)

    def start_run(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Autopiloto", "Ya hay una ejecucion en curso.")
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("Autopiloto", "Falta la API key.")
            return

        task = self.task_text.get("1.0", "end").strip()
        if not task:
            messagebox.showwarning("Autopiloto", "Describe una tarea antes de iniciar.")
            return

        model = self.model_var.get().strip() or DEFAULT_MODEL
        max_turns = max(1, int(self.max_turns_var.get()))
        safe_mode = bool(self.safe_mode_var.get())

        config = RunConfig(
            api_key=api_key,
            model=model,
            max_turns=max_turns,
            safe_mode=safe_mode,
        )

        self.stop_event.clear()
        self._set_running_state(True)
        self.queue_log("Inicio de ejecucion.")

        def worker() -> None:
            try:
                agent = WindowsAutopilotAgent(config, self.queue_log, self.stop_event)
                result = agent.run(task)
                self.ui_queue.put(("done", result))
            except StopRequested:
                self.ui_queue.put(("done", "Ejecucion detenida por el usuario."))
            except pyautogui.FailSafeException:
                self.ui_queue.put(
                    (
                        "error",
                        "PyAutoGUI FailSafe activado. Se detuvo la ejecucion (raton en esquina sup. izq.).",
                    )
                )
            except Exception as exc:
                details = f"{exc}\n\n{traceback.format_exc()}"
                self.ui_queue.put(("error", details))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def stop_run(self) -> None:
        self.stop_event.set()
        self.queue_log("Solicitud de parada enviada.")


def main() -> None:
    load_dotenv()
    root = tk.Tk()
    app = AppUI(root)
    app.log("App lista.")
    app.log("Consejo: empieza con tareas simples para calibrar el agente en tu equipo.")
    root.mainloop()


if __name__ == "__main__":
    main()
