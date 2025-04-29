import threading
import time
import socket
import traceback

# Importar los clientes Modbus
from modbus_client.tcp_client import ModbusTCPClient
from modbus_client.rtu_over_tcp_client import ModbusRtuOverTcpClient
# Importar excepciones personalizadas
from modbus_client.exceptions import ConnectionException, ModbusException
# Importar PollingService para llamarlo desde el monitor
from services.polling_service import PollingService # Asumiendo que está en el mismo paquete

class ServiceError(Exception):
    """Excepción personalizada para errores internos del servicio."""
    pass

# ==============================================================================
#   WORKER STANDALONE (con lógica real y resultado en dict)
# ==============================================================================
# (Sin cambios respecto a la versión anterior)
def connection_worker_standalone(log_service_arg, stop_event, result_dict, ip, port, unit_id, client_instance):
    thread_name = threading.current_thread().name
    print(f"WORKER_STANDALONE [{thread_name}]: ENTRANDO AL HILO (Real - Args: {ip}:{port} U:{unit_id} Client:{type(client_instance).__name__})")
    log_service_arg.log_info("WORKER_STANDALONE: Hilo (Real) iniciado.")
    success = False; error = None; final_message = "Worker no completado"
    max_retries_local = 6; retry_delay_local = 1.0
    try:
        print(f"WORKER_STANDALONE [{thread_name}]: Iniciando bucle conexión real.")
        log_service_arg.log_debug("WORKER_STANDALONE: Iniciando bucle conexión real.")
        for attempt in range(max_retries_local):
            log_service_arg.log_debug(f"WORKER_STANDALONE: Inicio intento {attempt + 1}/{max_retries_local}.")
            print(f"WORKER_STANDALONE: Inicio intento {attempt + 1}/{max_retries_local}.")
            if stop_event.is_set():
                log_service_arg.log_info("WORKER_STANDALONE: Cancelación detectada (inicio intento).")
                final_message = "Conexión cancelada."; error = ConnectionException("Cancelled by user"); success = False; break
            log_service_arg.log_info(f"Intentando conectar (intento {attempt + 1}/{max_retries_local})...")
            try:
                log_service_arg.log_debug(f"WORKER_STANDALONE: Llamando client_instance.connect({ip}, {port})...")
                print(f"WORKER_STANDALONE: Llamando client_instance.connect({ip}, {port})...")
                client_instance.connect(ip, port)
                log_service_arg.log_info("WORKER_STANDALONE: client_instance.connect() ÉXITO.")
                print("WORKER_STANDALONE: client_instance.connect() ÉXITO.")
                success = True; final_message = "Conectado exitosamente."
                log_service_arg.log_info(f"WORKER_STANDALONE: {final_message}")
                break
            except (ConnectionException, ModbusException, socket.error, Exception) as e:
                error = e
                log_service_arg.log_error(f"WORKER_STANDALONE: Intento {attempt + 1} fallido: {type(e).__name__}: {e}")
                print(f"WORKER_STANDALONE: Intento {attempt + 1} fallido: {type(e).__name__}: {e}")
                if attempt < max_retries_local - 1:
                    log_service_arg.log_debug(f"WORKER_STANDALONE: Esperando {retry_delay_local}s...")
                    cancelled = stop_event.wait(timeout=retry_delay_local)
                    if cancelled:
                        log_service_arg.log_info("WORKER_STANDALONE: Cancelado durante espera.")
                        final_message = "Conexión cancelada (espera)."; error = ConnectionException("Cancelled during retry wait"); success = False; break
                else:
                    final_message = f"Fallo conexión tras {max_retries_local} intentos: {e}"
                    log_service_arg.log_error(f"WORKER_STANDALONE: {final_message}"); success = False
        log_service_arg.log_debug("WORKER_STANDALONE: Fin del bucle.")
    except Exception as e:
        print(f"WORKER_STANDALONE [{thread_name}]: EXCEPCIÓN CRÍTICA: {type(e).__name__}: {e}")
        log_service_arg.log_critical(f"WORKER_STANDALONE: EXCEPCIÓN CRÍTICA: {type(e).__name__}: {e}", exc_info=True)
        error = e; success = False; final_message = f"Error interno crítico del worker: {e}"
    finally:
        print(f"WORKER_STANDALONE [{thread_name}]: FINALLY. Éxito={success}. Err={error}. Msg='{final_message}'")
        log_service_arg.log_info(f"WORKER_STANDALONE: FINALLY. Éxito={success}. Err={error}. Msg='{final_message}'")
        result_dict['success'] = success; result_dict['error'] = error; result_dict['final_message'] = final_message
        print(f"WORKER_STANDALONE [{thread_name}]: Hilo finalizado.")
        log_service_arg.log_info("WORKER_STANDALONE: Hilo finalizado.")


# ==============================================================================
#   CLASE ConnectionService
# ==============================================================================
class ConnectionService:
    def __init__(self, log_service, register_service, polling_service):
        self.log_service = log_service
        self.register_service = register_service
        self.polling_service = polling_service
        self.client = None
        self._keep_alive_thread = None; self._stop_keep_alive_event = threading.Event(); self.keep_alive_interval = 15
        self._state = {"connected": False, "is_connecting": False, "message": "Desconectado", "ip": None, "port": None, "unit_id": None, "mode": None, "uptime_seconds": 0, "last_error": None, "last_keep_alive_ok": None}
        self._state_lock = threading.Lock(); self._connection_thread = None; self._connection_thread_stop_event = threading.Event(); self._connection_thread_result = {}
        self.max_retries = 6; self.retry_delay = 1.0

    # --- Getters (sin cambios) ---
    def get_client(self):
        with self._state_lock: return self.client if self._state["connected"] else None

    def get_connection_status(self):
        with self._state_lock:
            if self._state["connected"] and self.client:
                 try: self._state["uptime_seconds"] = self.client.get_connection_uptime()
                 except Exception: self._state["uptime_seconds"] = 0
            return self._state.copy()

    # --- Métodos Internos de Estado (sin cambios) ---
    def _update_status(self, **kwargs):
        self.log_service.log_debug(f"_update_status: Entrando con kwargs={kwargs}")
        updated_keys = []
        with self._state_lock:
            for key, value in kwargs.items():
                if key in self._state:
                    if key == "last_error" and value == "CLEAR":
                        if self._state["last_error"] is not None: updated_keys.append(key)
                        self._state["last_error"] = None
                    elif self._state[key] != value:
                        updated_keys.append(key); self._state[key] = value
                elif key != 'uptime': self.log_service.log_warning(f"_update_status: Clave desconocida '{key}' ignorada.")
            if kwargs.get("connected") is False:
                if self._state["uptime_seconds"] != 0: updated_keys.append("uptime_seconds")
                if self._state["last_keep_alive_ok"] is not None: updated_keys.append("last_keep_alive_ok")
                self._state["uptime_seconds"] = 0; self._state["last_keep_alive_ok"] = None
            if kwargs.get("connected") is True:
                 if "last_error" not in kwargs or kwargs["last_error"] == "CLEAR":
                     if self._state["last_error"] is not None: updated_keys.append("last_error")
                     self._state["last_error"] = None
                 if self._state["uptime_seconds"] != 0: updated_keys.append("uptime_seconds_reset")
                 self._state["uptime_seconds"] = 0
        self.log_service.log_debug(f"_update_status: Saliendo. Claves actualizadas: {updated_keys if updated_keys else 'Ninguna'}.")

    def _reset_state_to_disconnected(self, message="Desconectado", error=None):
         tb_info = ""; client_temp = None
         if error and isinstance(error, Exception): tb_info = "\n" + "".join(traceback.format_exception(type(error), error, error.__traceback__))
         self.log_service.log_warning(f">>> _reset_state_to_disconnected (Msg: '{message}', Err: '{error}'){tb_info}")
         print(f"--- _reset_state_to_disconnected (Msg: '{message}', Err: '{error}') ---")
         with self._state_lock:
             client_temp = self.client; self.client = None
             # Llamada única a _update_status para resetear
             # Nota: _update_status maneja su propio lock, pero llamarlo desde aquí
             # donde ya tenemos el lock podría causar problemas si usamos RLock.
             # Es más seguro actualizar directamente el diccionario aquí.
             self._state["connected"] = False; self._state["is_connecting"] = False
             self._state["message"] = message; self._state["ip"] = None
             self._state["port"] = None; self._state["unit_id"] = None
             self._state["mode"] = None; self._state["uptime_seconds"] = 0
             self._state["last_error"] = str(error) if error else None
             self._state["last_keep_alive_ok"] = None
             self.log_service.log_debug(f"Estado DENTRO de reset: {self._state}")
         if client_temp:
             self.log_service.log_debug("Intentando desconectar cliente previo en reset...")
             try: client_temp.disconnect(acquire_lock=True)
             except Exception as e: self.log_service.log_error(f"Error (ignorado) al desconectar cliente previo en reset: {e}")
         self.log_service.log_debug(f"Estado reseteado completado.")


    # --- Pre-Check (CORREGIDO SyntaxError en finally) ---
    def _check_port_open(self, ip, port, timeout=1.0):
          sock = None; success = False
          try:
              self.log_service.log_debug(f"Pre-check: {ip}:{port} (T:{timeout}s)...")
              sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
              sock.settimeout(timeout)
              sock.connect((ip, port))
              success = True
              self.log_service.log_debug(f"Pre-check: OK.")
          except socket.timeout:
              self.log_service.log_warning(f"Pre-check: Timeout.")
          except socket.error as e:
              self.log_service.log_warning(f"Pre-check: Socket Error {e.errno} ({e.strerror}).") # Añadir strerror
          except Exception as e:
              self.log_service.log_error(f"Pre-check: Error Inesperado {e}.")
          finally:
              if sock:
                  # --- CORRECCIÓN AQUÍ ---
                  try:
                      sock.close()
                  except Exception:
                      pass # Ignorar errores al cerrar socket de prueba
                  # -----------------------
          return success

    # --- Método Connect (sin cambios respecto a la versión anterior) ---
    def connect(self, ip, port, unit_id, mode='tcp'):
         self.log_service.log_info(f"API Connect Request: IP={ip}, Port={port}, UnitID={unit_id}, Mode={mode}")
         print(f"CONNECT METHOD: START - IP={ip}, Port={port}, UnitID={unit_id}, Mode={mode}")
         local_client = None; thread_created = False; thread_started = False
         response_sent = False; connect_result = None; local_thread_obj = None
         try:
             with self._state_lock:
                 self.log_service.log_debug("CONNECT METHOD: Lock (check inicial).")
                 if self._state["is_connecting"] or self._state["connected"]:
                     msg = "Conexión ya activa/en progreso."; self.log_service.log_warning(f"CONNECT METHOD: Ignorado - {msg}"); print(f"CONNECT METHOD: Ignorado - {msg}")
                     return {"success": False, "message": msg}
                 self.log_service.log_debug("CONNECT METHOD: Estado verificado OK.")
             self.log_service.log_debug("CONNECT METHOD: Lock liberado (check inicial).")
             if not self._check_port_open(ip, int(port)):
                  error_msg = f"Pre-check fallido: No se pudo conectar a {ip}:{port}."
                  self.log_service.log_error(f"CONNECT METHOD: {error_msg}"); print(f"CONNECT METHOD: {error_msg}")
                  self._update_status(is_connecting=False, connected=False, message="Fallo de conexión", ip=ip, port=int(port), unit_id=int(unit_id), mode=mode, last_error=error_msg)
                  response_sent = True; return {"success": False, "message": error_msg}
             self.log_service.log_debug("CONNECT METHOD: Readquiriendo lock...")
             with self._state_lock:
                 self.log_service.log_debug("CONNECT METHOD: Lock (preparación).")
                 if self._state["is_connecting"] or self._state["connected"]:
                     msg = "CONNECT METHOD: Estado cambió. Ignorando."; self.log_service.log_warning(msg); print(msg)
                     return {"success": False, "message": "Proceso ya iniciado."}
                 self.log_service.log_info(f"CONNECT METHOD: Instanciando cliente ({mode.upper()})...")
                 try:
                      if mode == 'tcp': local_client = ModbusTCPClient()
                      elif mode == 'rtu_over_tcp': local_client = ModbusRtuOverTcpClient()
                      else: raise ValueError(f"Modo desconocido: {mode}")
                      local_client.set_log_service(self.log_service); self.client = local_client
                      self.log_service.log_debug(f"CONNECT METHOD: Cliente instanciado OK.")
                 except Exception as e: raise ServiceError(f"Fallo crear cliente {mode}: {e}") from e
                 if not self.client or not self.log_service: raise ServiceError("Cliente o LogService None.")
                 self.log_service.log_info(f"CONNECT METHOD: Preparando hilo worker (Real)...")
                 self._connection_thread_stop_event.clear(); self._connection_thread_result = {}
                 thread_args = (self.log_service, self._connection_thread_stop_event, self._connection_thread_result, ip, int(port), int(unit_id), self.client)
                 self.log_service.log_debug(f"CONNECT METHOD: Args listos."); print(f"CONNECT METHOD: Args listos.")
                 try:
                     self._connection_thread = threading.Thread(target=connection_worker_standalone, args=thread_args, name="ConnectionWorkerStandalone", daemon=True)
                     local_thread_obj = self._connection_thread; thread_created = True
                     self.log_service.log_debug("CONNECT METHOD: Instancia Thread creada OK."); print("CONNECT METHOD: Instancia Thread creada OK.")
                 except Exception as thread_init_err: raise ServiceError(f"Fallo creación hilo: {thread_init_err}") from thread_init_err
             self.log_service.log_debug("CONNECT METHOD: Lock liberado (preparación).")
             self.log_service.log_debug("CONNECT METHOD: Actualizando estado a 'conectando'...")
             print("CONNECT METHOD: Actualizando estado a 'conectando'...")
             try: self._update_status(is_connecting=True, connected=False, message="Conectando...", ip=ip, port=int(port), unit_id=int(unit_id), mode=mode, last_error="CLEAR")
             except Exception as update_err: raise ServiceError(f"Fallo al actualizar estado: {update_err}") from update_err
             self.log_service.log_info("CONNECT METHOD: Estado actualizado a 'conectando'.")
             print(f"CONNECT METHOD: Estado actualizado a 'conectando'.")
             self.log_service.log_debug("CONNECT METHOD: ===> ANTES de llamar a thread.start() <===")
             print(">>> Llamando a thread.start()...")
             if not local_thread_obj: raise ServiceError("Referencia al hilo perdida.")
             try:
                  local_thread_obj.start(); thread_started = True
                  self.log_service.log_info(f"CONNECT METHOD: Hilo REAL llamado a start() OK.")
                  print(f">>> Hilo worker REAL iniciado OK.")
                  self.log_service.log_debug("CONNECT METHOD: Iniciando monitor...")
                  threading.Thread(target=self._monitor_connection_worker, args=(self,), daemon=True, name="ConnWorkerMonitor").start()
                  self.log_service.log_debug("CONNECT METHOD: Monitor iniciado.")
             except BaseException as start_err: raise ServiceError(f"Fallo en start(): {start_err}") from start_err
             self.log_service.log_debug("CONNECT METHOD: Preparando respuesta JSON éxito...")
             print("CONNECT METHOD: Preparando respuesta JSON éxito...")
             connect_result = {"success": True, "message": f"Proceso de conexión ({mode.upper()}) iniciado..."}
             response_sent = True
         except (ServiceError, Exception) as connect_err:
             self.log_service.log_critical(f"CONNECT METHOD: Error capturado: {connect_err}", exc_info=True); print(f"CONNECT METHOD: Error capturado: {connect_err}")
             self._reset_state_to_disconnected(message="Error durante conexión", error=connect_err)
             if not response_sent: connect_result = {"success": False, "message": f"Error interno: {connect_err}"}
             else: self.log_service.log_error("CONNECT METHOD: Error DESPUÉS de preparar respuesta.")
         finally:
             self.log_service.log_debug("CONNECT METHOD: Entrando en finally principal.")
             print("CONNECT METHOD: Entrando en finally principal.")
             if not connect_result:
                  self.log_service.log_error("CONNECT METHOD: No se preparó respuesta, error genérico.")
                  connect_result = {"success": False, "message": "Error interno inesperado."}
         self.log_service.log_info(f"CONNECT METHOD: Retornando respuesta final.")
         print(f"CONNECT METHOD: Retornando respuesta final.")
         return connect_result # Devolver dict

    # --- Monitor (sin cambios necesarios) ---
    def _monitor_connection_worker(self, service_instance):
        active_thread = service_instance._connection_thread; log_svc = service_instance.log_service
        if not active_thread: log_svc.log_warning("Monitor: _connection_thread None."); return
        log_svc.log_debug(f"Monitor: Esperando worker '{active_thread.name}'..."); active_thread.join(); log_svc.log_debug(f"Monitor: Worker '{active_thread.name}' terminó.")
        result = service_instance._connection_thread_result; service_instance._connection_thread = None; log_svc.log_debug("Monitor: Ref hilo limpiada.")
        success = result.get('success', False); error = result.get('error', None); final_message_worker = result.get('final_message', '')
        if success:
            log_svc.log_info(f"Monitor: Worker OK. Msg='{final_message_worker}'. Actualizando estado..."); success_message = final_message_worker if final_message_worker else "Conectado"
            service_instance._update_status(connected=True, is_connecting=False, message=success_message)
            service_instance._start_keep_alive()
            log_svc.log_info("Monitor: Realizando lectura inicial...")
            try:
                 if service_instance.polling_service:
                     read_result = service_instance.polling_service.read_once()
                     log_svc.log_info(f"Monitor: Res lectura inicial: {read_result.get('message')}")
                     if not read_result.get('success'): service_instance._update_status(last_error=f"Lectura inicial falló: {read_result.get('message')}")
                 else: log_svc.log_error("Monitor: polling_service no disponible.")
            except Exception as read_err: log_svc.log_error(f"Monitor: Error lectura inicial: {read_err}", exc_info=True); service_instance._update_status(last_error=f"Error lectura inicial: {read_err}")
        else:
             error_to_report = str(error) if error else "Fallo desconocido"; message_to_report = final_message_worker if final_message_worker else error_to_report
             log_svc.log_error(f"Monitor: Worker FALLÓ. Msg='{message_to_report}'. Err='{error_to_report}'. Reseteando...")
             service_instance._reset_state_to_disconnected(message=message_to_report, error=error_to_report)
        log_svc.log_debug("Monitor terminado.")

    # --- disconnect (sin cambios necesarios) ---
    def disconnect(self, initiated_by_polling=False):
         thread_to_join = None; was_connecting = False; was_connected = False; client_to_disconnect = None
         success = True; final_message = "Desconectado exitosamente."
         with self._state_lock:
             was_connecting = self._state["is_connecting"]; was_connected = self._state["connected"]; current_mode = self._state["mode"]
             if not was_connected and not was_connecting:
                 if not initiated_by_polling: self.log_service.log_warning("Intento de desconectar sin conexión.")
                 return {"success": False, "message": "No estaba conectado."}
             self.log_service.log_info(f"Iniciando desconexión (Estado: {'Conectado' if was_connected else 'Conectando'}, Modo: {current_mode})...")
             self._stop_keep_alive()
             if was_connecting and self._connection_thread and self._connection_thread.is_alive():
                  self.log_service.log_info("Señalizando parada al hilo de conexión activo...")
                  self._connection_thread_stop_event.set(); thread_to_join = self._connection_thread
             client_to_disconnect = self.client; self.client = None
             self._update_status(is_connecting=False, connected=False, message="Desconectando...")
             self.register_service.clear_register_data()
         if thread_to_join:
             self.log_service.log_info("Esperando hilo termine tras señal...")
             thread_to_join.join(timeout=max(self.retry_delay, 2.0) + 1)
             if thread_to_join.is_alive(): self.log_service.log_warning("Hilo no terminó.")
             else: self.log_service.log_info("Hilo terminado.")
             self._connection_thread = None
         try: self._reset_state_to_disconnected(message=final_message)
         except Exception as e:
              final_message = f"Error crítico en desconexión: {e}"; success = False
              self.log_service.log_critical(final_message, exc_info=True)
         self.log_service.log_info(f"DISCONNECT: Proceso finalizado. Result: Success={success}, Msg='{final_message}'")
         print(f"DISCONNECT: Proceso finalizado. Result: Success={success}, Msg='{final_message}'")
         return {"success": success, "message": final_message}


    # --- Keep-Alive (sin cambios) ---
    def _start_keep_alive(self):
        if self._keep_alive_thread and self._keep_alive_thread.is_alive(): return
        self._stop_keep_alive_event.clear()
        self._keep_alive_thread = threading.Thread(target=self._keep_alive_worker, name="KeepAliveWorker", daemon=True)
        self._keep_alive_thread.start()
        self.log_service.log_info(f"[KeepAlive] Iniciado (intervalo {self.keep_alive_interval}s).")
    def _stop_keep_alive(self):
        if self._keep_alive_thread:
            if self._keep_alive_thread.is_alive(): self.log_service.log_info("[KeepAlive] Deteniendo..."); self._stop_keep_alive_event.set()
            else: self._stop_keep_alive_event.set()
            self._keep_alive_thread = None
    def _keep_alive_worker(self):
        self.log_service.log_info("[KeepAlive] Hilo iniciado.")
        while not self._stop_keep_alive_event.is_set():
            cancelled = self._stop_keep_alive_event.wait(timeout=self.keep_alive_interval);
            if cancelled: self.log_service.log_info("[KeepAlive] Evento parada."); break
            ka_client = None; ka_unit_id = None; is_conn = False
            with self._state_lock:
                is_conn = self._state["connected"] and not self._state["is_connecting"]
                if is_conn and self.client: ka_client = self.client; ka_unit_id = self._state["unit_id"]
            if not is_conn: self.log_service.log_info("[KeepAlive] No conectado."); break
            if ka_client and ka_unit_id is not None:
                self.log_service.log_debug("[KeepAlive] Lectura prueba...")
                ka_time = time.time()
                try:
                    vals = ka_client.read_holding_registers(ka_unit_id, 0, 1)
                    self.log_service.log_debug(f"[KeepAlive] Lectura OK: {vals}")
                    self._update_status(last_keep_alive_ok=ka_time)
                except (ConnectionException, socket.error, socket.timeout) as e:
                     err_msg = f"[KeepAlive] FALLO CONEXIÓN: {e}"; self.log_service.log_error(err_msg + ". Desconectando..."); self.disconnect(True); break
                except ModbusException as e:
                     warn_msg = f"[KeepAlive] Error Modbus (Conexión OK): {e}"; self.log_service.log_warning(warn_msg); self._update_status(last_keep_alive_ok=ka_time)
                except Exception as e:
                     crit_msg = f"[KeepAlive] Error inesperado: {e}"; self.log_service.log_critical(crit_msg + ". Desconectando...", exc_info=True); self.disconnect(True); break
            else: self.log_service.log_warning("[KeepAlive] Inconsistente."); break
        self.log_service.log_info("[KeepAlive] Hilo terminado."); self._keep_alive_thread = None