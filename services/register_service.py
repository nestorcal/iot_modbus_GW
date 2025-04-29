# services/register_service.py
import time
import threading

class RegisterService:
    def __init__(self, log_service):
        self.log_service = log_service
        self._registers = {
            "start_addr": 0,
            "count": 10,
            "values": [],       # Últimos valores leídos (números crudos)
            "last_update": None,
        }
        self._register_lock = threading.Lock()

    def update_read_parameters(self, start_addr, count):
        """Actualiza los parámetros para la lectura de registros."""
        with self._register_lock:
            try:
                new_start_addr = int(start_addr)
                new_count = int(count)
                if not (0 <= new_start_addr <= 65535):
                    raise ValueError("Dirección inicial fuera de rango (0-65535).")
                if not (0 <= new_count <= 125): # Permitir 0
                    raise ValueError("Cantidad fuera de rango (0-125).")

                changed = (self._registers["start_addr"] != new_start_addr or
                           self._registers["count"] != new_count)

                self._registers["start_addr"] = new_start_addr
                self._registers["count"] = new_count

                if changed:
                    # Limpiar valores antiguos si los parámetros cambian
                    self._registers["values"] = []
                    self._registers["last_update"] = None
                    self.log_service.log_info(f"Parámetros de lectura actualizados: Addr={new_start_addr}, Count={new_count}")
                else:
                     self.log_service.log_info(f"Parámetros de lectura sin cambios (Addr={new_start_addr}, Count={new_count}).")

                return {"success": True, "message": "Parámetros actualizados."}

            except (ValueError, TypeError) as e:
                self.log_service.log_warning(f"Intento de actualizar parámetros con valores inválidos: {e}")
                return {"success": False, "message": f"Valores inválidos: {e}"}

    def get_read_parameters(self):
        """Obtiene los parámetros de lectura actuales."""
        with self._register_lock:
            return self._registers["start_addr"], self._registers["count"]

    def update_register_values(self, new_values):
        """Actualiza los valores de los registros leídos."""
        with self._register_lock:
            self._registers["values"] = new_values
            self._registers["last_update"] = time.time()
            # self.log_service.log_debug(f"Valores de registro actualizados: {new_values}") # Puede ser muy verboso

    def get_register_data(self):
        """Devuelve los últimos datos de registros leídos y sus parámetros."""
        with self._register_lock:
            # Devuelve una copia
            return self._registers.copy()

    def clear_register_data(self):
        """Limpia los valores de registros almacenados."""
        with self._register_lock:
            self._registers["values"] = []
            self._registers["last_update"] = None
            self.log_service.log_info("Datos de registros limpiados.")
