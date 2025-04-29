"""
import time
import threading
import socket
from collections import deque
from modbus_client.client import ModbusTCPClient
from modbus_client.exceptions import ModbusException, ConnectionException

class ModbusDataService:
    def __init__(self, max_log_size=100, max_retries=6, retry_delay=1.0):
        self.client = ModbusTCPClient()
        self.client.set_debug_log_handler(self._add_log_entry)
        self.lock = threading.Lock()
        self._status = {
            "connected": False,
            "message": "Desconectado",
            "ip": None,
            "port": None,
            "unit_id": None,
            "uptime_seconds": 0,
            "last_error": None,
            "is_connecting": False,
        }
        # El diccionario _registers SÍ existe
        self._registers = {
            "start_addr": 0,
            "count": 10,
            "values": [],
            "last_update": None,
        }
        self._debug_log = deque(maxlen=max_log_size)
        self._polling_thread = None
        self._stop_polling_event = threading.Event()
        self.poll_interval = 2.0
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _add_log_entry(self, message):
        with self.lock:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self._debug_log.append(f"{timestamp} - {message}")

    # --- connect, disconnect, _polling_loop (como en la respuesta anterior) ---
    def connect(self, ip, port, unit_id):
        # ... (código de connect con reintentos, sin cambios) ...
        with self.lock:
            if self._status["connected"] or self._status["is_connecting"]:
                msg = "Conexión ya activa." if self._status["connected"] else "Conexión ya en progreso."
                self._add_log_entry(f"[SERVICE] {msg}")
                return {"success": False, "message": msg}
            self._status["is_connecting"] = True
            self._status["message"] = "Iniciando conexión..."
            self._status["ip"] = ip
            self._status["port"] = int(port)
            self._status["unit_id"] = int(unit_id)
            self._status["last_error"] = None
        connection_successful = False
        final_message = ""
        connect_exception = None
        for attempt in range(self.max_retries):
            with self.lock:
                if not self._status["is_connecting"]:
                     self._add_log_entry("[SERVICE] Intento de conexión cancelado.")
                     # Ya no estamos conectando, así que reseteamos is_connecting aquí también
                     self._status["is_connecting"] = False
                     return {"success": False, "message": "Conexión cancelada."}
                attempt_msg = f"Intentando conectar (intento {attempt + 1}/{self.max_retries})..."
                self._status["message"] = attempt_msg
                self._add_log_entry(f"[SERVICE] {attempt_msg} a {ip}:{port} (UnitID: {unit_id})")
            try:
                self.client.connect(ip, int(port))
                connection_successful = True
                with self.lock:
                    # Doble check por si disconnect fue llamado mientras conectaba fuera del lock
                    if not self._status["is_connecting"]:
                        self._add_log_entry("[SERVICE] Conexión exitosa pero cancelada justo después.")
                        connection_successful = False # Marcar como no exitosa al final
                        self.client.disconnect() # Desconectar lo que acabamos de conectar
                        break # Salir del bucle de reintentos
                    self._status["connected"] = True
                    self._status["message"] = "Conectado"
                    final_message = "Conectado exitosamente."
                    self._add_log_entry(f"[SERVICE] {final_message}")
                    self._stop_polling_event.clear()
                    if self._polling_thread is None or not self._polling_thread.is_alive():
                        self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
                        self._polling_thread.start()
                        self._add_log_entry("[SERVICE] Hilo de polling iniciado.")
                break
            except (ConnectionException, socket.error, ValueError, Exception) as e:
                connect_exception = e
                self._add_log_entry(f"[SERVICE] Intento {attempt + 1} fallido: {e}")
                if attempt < self.max_retries - 1:
                     with self.lock:
                         # Solo actualizar mensaje si todavía estamos intentando conectar
                         if self._status["is_connecting"]:
                            self._status["message"] = f"Intento {attempt + 1} fallido. Reintentando..."
                     # Salir del bucle si se canceló durante el sleep
                     if self._stop_polling_event.wait(timeout=self.retry_delay): # Usar wait en lugar de sleep
                         with self.lock:
                             if not self._status["is_connecting"]: # Re-chequear si se canceló
                                 self._add_log_entry("[SERVICE] Conexión cancelada durante el reintento.")
                                 break # Salir del bucle for
                else:
                     final_message = f"Fallo la conexión tras {self.max_retries} intentos: {e}"
                     self._add_log_entry(f"[SERVICE] {final_message}")
                     with self.lock:
                         # Solo actualizar estado si no se canceló mientras tanto
                         if self._status["is_connecting"]:
                             self._status["message"] = final_message
                             self._status["last_error"] = str(e)
                             self._status["connected"] = False
                             self._status["ip"] = None
                             self._status["port"] = None
                             self._status["unit_id"] = None
        # --- Finalizar el estado de conexión ---
        with self.lock:
             self._status["is_connecting"] = False # Siempre marcar como terminado el intento
             if not connection_successful:
                 # Asegurar estado limpio si falló o fue cancelado
                 self._status["connected"] = False
                 self._status["ip"] = None
                 self._status["port"] = None
                 self._status["unit_id"] = None
                 self._status["last_error"] = str(connect_exception) if connect_exception else "Conexión fallida o cancelada."
                 self._status["message"] = final_message if final_message else "Conexión fallida."
                 # Asegurarse de que el cliente esté desconectado si falló
                 if self.client.is_connected:
                      try:
                          self.client.disconnect()
                      except Exception as disconn_err:
                           self._add_log_entry(f"[SERVICE][WARN] Error al desconectar cliente tras fallo de conexión: {disconn_err}")

        return {"success": connection_successful, "message": final_message}

    def disconnect(self):
        # ... (código de disconnect, sin cambios) ...
        with self.lock:
            was_connecting = self._status["is_connecting"]
            if not self._status["connected"] and not was_connecting:
                self._add_log_entry("[SERVICE] Intento de desconectar sin conexión activa o en progreso.")
                return {"success": False, "message": "No estaba conectado."}
            self._add_log_entry("[SERVICE] Iniciando desconexión...")
            self._status["is_connecting"] = False # Cancelar intento de conexión
            self._stop_polling_event.set() # Señal para detener el hilo de polling
            polling_thread_to_join = self._polling_thread
            self._polling_thread = None
        if polling_thread_to_join and polling_thread_to_join.is_alive():
            self._add_log_entry("[SERVICE] Esperando que el hilo de polling termine...")
            polling_thread_to_join.join(timeout=max(self.poll_interval, self.retry_delay) + 1) # Esperar un poco más
            if polling_thread_to_join.is_alive():
                self._add_log_entry("[WARN] El hilo de polling no se detuvo a tiempo.")
        disconnect_message = "Desconectado exitosamente."
        disconnect_success = True
        try:
             if self.client.is_connected:
                 self.client.disconnect()
             else:
                  # Si estábamos conectando y se canceló, el cliente podría no haberse conectado nunca
                 self._add_log_entry("[SERVICE] Cliente ya estaba desconectado o nunca se conectó.")
        except Exception as e:
             self._add_log_entry(f"[ERROR] Error durante la desconexión del cliente: {e}")
             disconnect_message = f"Error al desconectar: {e}"
             disconnect_success = False
        finally:
             with self.lock:
                 # Asegurarse de limpiar todo el estado relacionado con la conexión
                 self._status["connected"] = False
                 self._status["is_connecting"] = False # Asegurar que no quede en estado conectando
                 self._status["message"] = disconnect_message if disconnect_success else f"Desconectado con error: {disconnect_message}"
                 self._status["ip"] = None
                 self._status["port"] = None
                 self._status["unit_id"] = None
                 self._status["uptime_seconds"] = 0
                 self._registers["values"] = [] # Limpiar registros
                 self._registers["last_update"] = None
                 if not disconnect_success:
                     self._status["last_error"] = disconnect_message
                 else:
                     self._status["last_error"] = None # Limpiar error si desconexión fue ok
                 self._add_log_entry(f"[SERVICE] Desconexión completada (Éxito: {disconnect_success}).")
        return {"success": disconnect_success, "message": disconnect_message}

    def _polling_loop(self):
        # ... (código de _polling_loop, sin cambios) ...
        self._add_log_entry("[POLL] Polling loop iniciado.")
        while not self._stop_polling_event.is_set():
            start_time = time.time()
            read_success = False
            current_unit_id = None
            current_start_addr = 0
            current_count = 0
            with self.lock:
                if not self._status["connected"] or self._status["is_connecting"]:
                    break
                current_unit_id = self._status["unit_id"]
                current_start_addr = self._registers["start_addr"]
                current_count = self._registers["count"]
                try:
                   self._status["uptime_seconds"] = self.client.get_connection_uptime()
                except Exception as uptime_err:
                    self._add_log_entry(f"[POLL][WARN] Error al obtener uptime: {uptime_err}")
                    self._status["uptime_seconds"] = 0 # Resetear si hay error
            if current_unit_id is not None and current_count > 0: # Añadir check de count > 0
                try:
                    new_values = self.client.read_holding_registers(
                        current_unit_id, current_start_addr, current_count
                    )
                    with self.lock:
                        if self._status["connected"] and not self._status["is_connecting"] and not self._stop_polling_event.is_set():
                            self._registers["values"] = new_values
                            self._registers["last_update"] = time.time()
                            self._status["last_error"] = None
                            # Mantener mensaje "Conectado" estable
                            # self._status["message"] = "Conectado y leyendo"
                            read_success = True
                except (ModbusException, ConnectionException, socket.error, ValueError) as e:
                    self._add_log_entry(f"[POLL][ERROR] Error en lectura: {e}")
                    with self.lock:
                        # Solo actualizar si todavía estamos supuestamente conectados
                        if self._status["connected"]:
                            self._status["last_error"] = str(e)
                            self._status["message"] = f"Error de lectura: {type(e).__name__}"
                            if isinstance(e, ConnectionException) or isinstance(e, socket.error):
                                 self._add_log_entry("[POLL] Conexión perdida detectada durante polling.")
                                 self._status["connected"] = False
                                 self._status["message"] = "Conexión perdida"
                                 self._status["uptime_seconds"] = 0
                                 # Intentar limpiar el cliente
                                 try:
                                     if self.client.is_connected:
                                          self.client.disconnect()
                                 except Exception as disconn_poll_err:
                                      self._add_log_entry(f"[POLL][WARN] Error desconectando cliente tras error de lectura: {disconn_poll_err}")
                                 self._stop_polling_event.set() # Detener este bucle
                except Exception as e:
                     self._add_log_entry(f"[POLL][CRITICAL] Error inesperado: {e}")
                     with self.lock:
                         if self._status["connected"]: # Solo si estábamos conectados
                             self._status["last_error"] = str(e)
                             self._status["message"] = "Error inesperado en polling"
                             self._status["connected"] = False
                             self._status["uptime_seconds"] = 0
                             try:
                                 if self.client.is_connected:
                                      self.client.disconnect()
                             except Exception as disconn_crit_err:
                                  self._add_log_entry(f"[POLL][WARN] Error desconectando cliente tras error crítico: {disconn_crit_err}")
                             self._stop_polling_event.set() # Detener bucle
            elif current_count <= 0:
                # Si la cantidad es 0, no intentar leer, esperar al intervalo
                 self._add_log_entry("[POLL] Cantidad de registros es 0, omitiendo lectura.")
                 time.sleep(0.1) # Pequeña pausa para evitar spin-loop si poll_interval es corto


            # Control del intervalo de polling
            elapsed = time.time() - start_time
            sleep_time = self.poll_interval - elapsed
            if sleep_time > 0 and not self._stop_polling_event.is_set():
                 self._stop_polling_event.wait(timeout=sleep_time)
        self._add_log_entry("[POLL] Polling loop detenido.")


    # --- Métodos Getters y Setters ---


    def get_status(self):
        # Devuelve el estado actual de la conexión y parámetros.
        with self.lock:
            if self._status["connected"] and not self._status["is_connecting"]:
                 try:
                     self._status["uptime_seconds"] = self.client.get_connection_uptime()
                 except Exception: # Si get_connection_uptime falla
                     self._status["uptime_seconds"] = 0
            elif not self._status["connected"]:
                 self._status["uptime_seconds"] = 0
            return self._status.copy()

    # MÉTODO AÑADIDO AQUÍ
    def get_register_data(self):
        # Devuelve los últimos datos de registros leídos.
        with self.lock:
            # Devuelve una copia del diccionario interno _registers
            return self._registers.copy()

    def get_debug_log(self):
        # Devuelve las últimas entradas del log de depuración.
        with self.lock:
            return list(self._debug_log)

    def update_read_parameters(self, start_addr, count):
        # Actualiza los parámetros para la lectura de registros.
        with self.lock:
             try:
                 new_start_addr = int(start_addr)
                 new_count = int(count)
                 # Permitir cantidad 0, útil para pausar lecturas sin desconectar
                 if not (0 <= new_start_addr <= 65535):
                     raise ValueError("Dirección inicial fuera de rango (0-65535).")
                 if not (0 <= new_count <= 125): # Permitir 0
                     raise ValueError("Cantidad fuera de rango (0-125).")

                 if self._registers["start_addr"] != new_start_addr or self._registers["count"] != new_count:
                     self._registers["start_addr"] = new_start_addr
                     self._registers["count"] = new_count
                     # Limpiar valores antiguos sólo si los parámetros cambian
                     self._registers["values"] = []
                     self._registers["last_update"] = None
                     self._add_log_entry(f"[SERVICE] Parámetros de lectura actualizados: Addr={new_start_addr}, Count={new_count}")
                     # No es necesario reiniciar el polling loop, leerá los nuevos params en la siguiente iteración
                 else:
                      self._add_log_entry(f"[SERVICE] Parámetros de lectura sin cambios (Addr={new_start_addr}, Count={new_count}).")

                 return {"success": True, "message": "Parámetros actualizados."}

             except (ValueError, TypeError) as e:
                 self._add_log_entry(f"[SERVICE][WARN] Intento de actualizar parámetros con valores inválidos: {e}")
                 return {"success": False, "message": f"Valores inválidos: {e}"}

"""