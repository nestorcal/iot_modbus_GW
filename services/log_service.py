# services/log_service.py
import time
import traceback # Para formatear tracebacks
from collections import deque
import threading

class LogService:
    def __init__(self, max_log_size=250): # Aumentar tamaño un poco
        self._debug_log = deque(maxlen=max_log_size)
        self._log_lock = threading.Lock()

    def _add_entry(self, level, message, exc_info=False): # Aceptar exc_info
        """Añade una entrada al log, opcionalmente con traceback."""
        full_message = message
        # Si exc_info es True, obtener y añadir el traceback formateado
        if exc_info:
            try:
                # format_exc() devuelve el traceback de la excepción actual
                exc_text = traceback.format_exc()
                full_message += f"\nTraceback:\n{exc_text}"
            except Exception:
                # Por si format_exc falla por alguna razón
                full_message += "\n(Error al obtener traceback)"

        with self._log_lock:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            thread_name = threading.current_thread().name
            # Formato [LEVEL][ThreadName] Mensaje
            log_entry = f"{timestamp} [{level}][{thread_name}] {full_message}"
            print(log_entry) # Imprimir siempre a consola
            self._debug_log.append(log_entry)

    # Métodos públicos ahora aceptan exc_info
    def log_debug(self, message, exc_info=False):
        self._add_entry("DEBUG", message, exc_info)

    def log_info(self, message, exc_info=False):
        self._add_entry("INFO", message, exc_info)

    def log_warning(self, message, exc_info=False):
        self._add_entry("WARN", message, exc_info)

    def log_error(self, message, exc_info=False):
        self._add_entry("ERROR", message, exc_info)

    def log_critical(self, message, exc_info=False):
         self._add_entry("CRITICAL", message, exc_info)

    def get_logs(self):
        """Devuelve las últimas entradas del log."""
        with self._log_lock:
            return list(self._debug_log)

    def clear_logs(self):
        """Limpia la cola de logs."""
        with self._log_lock:
            self._debug_log.clear()
            self.log_info("Logs limpiados.") # Loguear la acción

    def get_logs_as_text(self):
        """Devuelve todos los logs como una sola cadena."""
        with self._log_lock:
            return "\n".join(self._debug_log)

    def save_logs_to_file(self, filename="modbus_web_log.txt"):
        """Guarda los logs actuales en un archivo."""
        # Implementación futura (o quitar si no se necesita)
        self.log_warning(f"Función save_logs_to_file no implementada (Archivo: {filename}).")
        pass

