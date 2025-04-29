# services/polling_service.py
import threading
import time
import socket # Para errores específicos
from modbus_client.exceptions import ModbusException, ConnectionException, ModbusIOException

class PollingService:
    def __init__(self, log_service, connection_service, register_service):
        """Inicializa el servicio para lecturas bajo demanda."""
        self.log_service = log_service
        self.connection_service = connection_service
        self.register_service = register_service
        self._read_lock = threading.Lock()

    def read_once(self):
        """Realiza una única lectura bajo demanda."""
        # --- Log de Inicio Claro ---
        self.log_service.log_info(">>> PollingService: Solicitud read_once() recibida.")
        print(">>> PollingService: Solicitud read_once() recibida.")
        # ---------------------------

        if not self._read_lock.acquire(blocking=False):
            self.log_service.log_warning("PollingService: Lectura ya en progreso. Omitiendo.")
            return {"success": False, "message": "Lectura ya en progreso."}

        read_success = False
        result_message = "Fallo desconocido durante lectura."
        registers_read = None

        try:
            status = self.connection_service.get_connection_status()
            if not status["connected"]:
                 result_message = "No conectado."
                 self.log_service.log_warning(f"PollingService: {result_message}")
                 return {"success": False, "message": result_message}

            modbus_client = self.connection_service.get_client()
            start_addr, count = self.register_service.get_read_parameters()
            unit_id = status["unit_id"]

            if not modbus_client: result_message = "Error: Cliente no disponible."; self.log_service.log_error(f"PollingService: {result_message}"); return {"success": False, "message": result_message}
            if unit_id is None: result_message = "Unit ID no configurado."; self.log_service.log_warning(f"PollingService: {result_message}"); return {"success": False, "message": result_message}

            if count <= 0:
                 result_message = f"Lectura omitida (Cantidad={count})."; self.log_service.log_info(f"PollingService: {result_message}"); return {"success": True, "message": result_message, "data": []}

            # --- Log Antes de Leer ---
            self.log_service.log_info(f"PollingService: Intentando leer {count} Holding Registers desde {start_addr} (Unit: {unit_id})...")
            print(f"PollingService: Intentando leer {count} Holding Registers desde {start_addr} (Unit: {unit_id})...")
            # -------------------------
            try:
                registers_read = modbus_client.read_holding_registers(unit_id, start_addr, count)
                read_success = True
                result_message = f"Lectura exitosa: {len(registers_read)} registros leídos."
                self.log_service.log_info(f"PollingService: {result_message} Valores: {registers_read}") # Loguear valores leídos
                print(f"PollingService: {result_message} Valores: {registers_read}")

            # --- Manejo de Excepciones (sin cambios, pero los logs ahora tienen 'PollingService') ---
            except (ModbusIOException, ModbusInvalidResponseException) as e: result_message = f"Error Modbus en lectura: {e}"; self.log_service.log_error(f"PollingService: {result_message}"); read_success = False
            except (ConnectionException, socket.error, socket.timeout) as e: result_message = f"Error conexión/socket en lectura: {e}"; self.log_service.log_error(f"PollingService: {result_message}. Desconectando..."); self.connection_service.disconnect(initiated_by_polling=True); read_success = False
            except ValueError as e: result_message = f"Error parámetros lectura: {e}"; self.log_service.log_error(f"PollingService: {result_message}"); read_success = False
            except Exception as e: result_message = f"Error inesperado lectura: {e}"; self.log_service.log_critical(f"PollingService: {result_message}", exc_info=True); read_success = False

            if read_success and registers_read is not None:
                self.register_service.update_register_values(registers_read)

            return {"success": read_success, "message": result_message, "data": registers_read if read_success else None}

        finally:
            self._read_lock.release()
            self.log_service.log_debug("PollingService: read_once - Lock liberado.")