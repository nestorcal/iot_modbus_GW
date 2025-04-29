import socket
import struct
import time
# import logging # Ya no usamos logging interno, usamos el LogService inyectado
import threading # Para obtener nombre de hilo
from .exceptions import ConnectionException, ModbusIOException, ModbusInvalidResponseException
from .formatter import DataFormatter

# logger = logging.getLogger(__name__) # Quitar

class ModbusTCPClient:
    def __init__(self):
        self.ip = None
        self.port = None
        self.sock = None
        self.transaction_id = 0
        self.is_connected = False
        self.connection_start_time = None
        self._log_service = None # Cambiar nombre para claridad
        self._client_lock = threading.Lock() # Lock para operaciones del socket

    def set_log_service(self, log_service):
        """Establece el servicio de logging a usar."""
        self._log_service = log_service

    def _log(self, level, message, layer="MODBUS_CLIENT"):  # O RTU_CLIENT
        if self._log_service:
            log_msg = f"[{layer}] {message}"
            if level == "DEBUG":
                self._log_service.log_debug(log_msg)
            elif level == "INFO":
                self._log_service.log_info(log_msg)
            elif level == "WARN":
                self._log_service.log_warning(log_msg)
            elif level == "ERROR":
                self._log_service.log_error(log_msg)
            elif level == "CRITICAL":
                self._log_service.log_critical(log_msg)
            else:  # Default a debug si nivel es desconocido
                self._log_service.log_debug(f"[UNKNOWN_LVL:{level}] {log_msg}")
        # else: # Opcional: imprimir si no hay logger
        #     print(f"[{level}][{layer}] {message}")


    def connect(self, ip, port, timeout=5):
        """Establece conexión (síncrona). Lanza excepción en fallo."""
        # Este método AHORA ES SÍNCRONO y será llamado desde un hilo por ConnectionService
        with self._client_lock: # Proteger acceso a self.sock y estado
            if self.is_connected:
                # Esto no debería pasar si ConnectionService lo maneja bien, pero por si acaso
                self._log("WARN", "Intento de conectar cuando ya está conectado.", layer="SOCKET")
                # Podríamos desconectar primero o simplemente retornar
                # self.disconnect(acquire_lock=False) # Desconectar sin re-adquirir lock
                # self._log("INFO", "Desconexión previa forzada.", layer="SOCKET")
                # Alternativamente, lanzar una excepción o advertencia
                raise ConnectionException("Cliente ya está conectado.")


            self.ip = ip
            self.port = port
            self.transaction_id = 0 # Resetear en cada conexión

            self._log("INFO", f"Intentando conectar a {self.ip}:{self.port} (Timeout: {timeout}s)...", layer="SOCKET")
            temp_sock = None # Usar socket temporal para no afectar self.sock hasta éxito
            try:
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(timeout)
                temp_sock.connect((self.ip, self.port))

                # Éxito, ahora actualizar estado del cliente
                self.sock = temp_sock
                self.is_connected = True
                self.connection_start_time = time.time()
                self._log("INFO", f"Conexión establecida con {self.ip}:{self.port}", layer="SOCKET")
                # No retornamos True/False, el éxito es no lanzar excepción

            except socket.timeout:
                self._log("ERROR", f"Timeout ({timeout}s) al conectar a {self.ip}:{self.port}", layer="SOCKET")
                if temp_sock: temp_sock.close()
                # Limpiar estado por si acaso
                self.sock = None
                self.is_connected = False
                self.connection_start_time = None
                raise ConnectionException(f"Timeout al conectar a {self.ip}:{self.port}")
            except Exception as e:
                self._log("ERROR", f"Error de conexión a {self.ip}:{self.port}: {e}", layer="SOCKET")
                if temp_sock: temp_sock.close()
                self.sock = None
                self.is_connected = False
                self.connection_start_time = None
                raise ConnectionException(f"Error de conexión: {e}")

    def disconnect(self, acquire_lock=True):
        """Cierra la conexión del socket."""
        # acquire_lock=False es para llamadas internas donde el lock ya está adquirido
        lock = self._client_lock if acquire_lock else None
        if lock: lock.acquire()
        try:
            if self.sock:
                self._log("INFO", "Cerrando socket...", layer="SOCKET")
                try:
                    # Shutdown puede ayudar a cerrar limpiamente en algunos casos
                    # self.sock.shutdown(socket.SHUT_RDWR)
                    self.sock.close()
                    self._log("INFO", "Socket cerrado.", layer="SOCKET")
                except Exception as e:
                    self._log("ERROR", f"Error al cerrar socket: {e}", layer="SOCKET")
                finally:
                    self.sock = None
                    self.is_connected = False
                    self.connection_start_time = None
            else:
                # Loguear sólo si no se espera que esté desconectado
                # self._log("DEBUG", "Intento de desconectar sin socket activo.", layer="SOCKET")
                self.is_connected = False # Asegurar estado
                self.connection_start_time = None
        finally:
            if lock: lock.release()

    def get_connection_uptime(self):
        """Devuelve el tiempo de conexión activo en segundos."""
        # No necesita lock si sólo lee valores que se setean juntos
        if self.is_connected and self.connection_start_time:
            return time.time() - self.connection_start_time
        return 0

    def _build_modbus_frame(self, unit_id, function_code, starting_address, quantity):
        # ... (sin cambios, pero usar self._log para debug) ...
        self.transaction_id = (self.transaction_id + 1) & 0xFFFF
        protocol_id = 0
        pdu = struct.pack('>BHH', function_code, starting_address, quantity)
        length = len(pdu) + 1
        mbap_header = struct.pack('>HHHB', self.transaction_id, protocol_id, length, unit_id)
        frame = mbap_header + pdu
        self._log("DEBUG", f"Frame construido (TID: {self.transaction_id}): {frame.hex()}", layer="MB_SENT")
        return frame

    def _send_request(self, request):
        """Envía una solicitud y recibe la respuesta (síncrono)."""
        # Este método es crítico y debe ser protegido por el lock
        with self._client_lock:
            if not self.is_connected or not self.sock:
                self._log("ERROR", "Intento de enviar request sin conexión.", layer="SOCKET")
                raise ConnectionException("No conectado al servidor Modbus.")

            try:
                self._log("DEBUG", f"Enviando {len(request)} bytes: {request.hex()}", layer="TCP")
                self.sock.sendall(request)

                # Leer cabecera MBAP (7 bytes)
                mbap_header_bytes = self._recv_all(7)
                if len(mbap_header_bytes) < 7:
                    raise ModbusInvalidResponseException(f"Respuesta incompleta (MBAP header). Recibidos {len(mbap_header_bytes)}/7 bytes.")

                self._log("DEBUG", f"MBAP Recibido: {mbap_header_bytes.hex()}", layer="MB_RECV")
                rx_trans_id, rx_proto_id, rx_length, rx_unit_id = struct.unpack('>HHHB', mbap_header_bytes)

                # Validar TID aquí mismo
                if rx_trans_id != self.transaction_id:
                    # Leer y descartar el resto según length para limpiar el buffer
                    bytes_to_discard = rx_length - 1
                    if bytes_to_discard > 0:
                         self._log("WARN", f"TID no coincide (Esperado: {self.transaction_id}, Recibido: {rx_trans_id}). Descartando {bytes_to_discard} bytes.", layer="MB_ERROR")
                         try:
                             self._recv_all(bytes_to_discard) # Intenta leer el resto
                         except Exception as discard_err:
                              self._log("ERROR", f"Error al descartar bytes de respuesta inválida: {discard_err}", layer="MB_ERROR")
                              # La conexión puede estar corrupta, forzar desconexión
                              self.disconnect(acquire_lock=False)
                              raise ConnectionException("Error de sincronización de TID y error al limpiar buffer.")
                    else:
                        self._log("WARN", f"TID no coincide (Esperado: {self.transaction_id}, Recibido: {rx_trans_id}). No hay datos adicionales que descartar.", layer="MB_ERROR")

                    raise ModbusInvalidResponseException(f"ID de transacción no coincide. Esperado: {self.transaction_id}, Recibido: {rx_trans_id}")

                # Leer PDU
                pdu_length = rx_length - 1 # Length incluye Unit ID ya leído
                if pdu_length < 1: # PDU debe tener al menos código de función (o func+error)
                     raise ModbusInvalidResponseException(f"Longitud de PDU inválida en respuesta ({pdu_length}). MBAP Length: {rx_length}")

                self._log("DEBUG", f"Esperando {pdu_length} bytes de PDU...", layer="TCP")
                pdu_bytes = self._recv_all(pdu_length)
                if len(pdu_bytes) < pdu_length:
                     raise ModbusInvalidResponseException(f"Respuesta incompleta (PDU). Esperados {pdu_length}, recibidos {len(pdu_bytes)} bytes.")

                self._log("DEBUG", f"PDU Recibido: {pdu_bytes.hex()}", layer="MB_RECV")
                response_pdu = pdu_bytes

                # Devolver unit_id también para validación externa si se desea
                return rx_unit_id, response_pdu

            except socket.timeout:
                self._log("ERROR", "Timeout durante send/recv.", layer="SOCKET")
                self.disconnect(acquire_lock=False) # Forzar desconexión interna
                raise ConnectionException("Timeout en la comunicación Modbus.")
            except socket.error as e:
                 self._log("ERROR", f"Error de Socket en send/recv: {e}", layer="SOCKET")
                 self.disconnect(acquire_lock=False) # Forzar desconexión interna
                 raise ConnectionException(f"Error de Socket en comunicación: {e}")
            except ModbusException as e: # Re-lanzar excepciones Modbus específicas
                 raise e
            except Exception as e:
                 self._log("CRITICAL", f"Error inesperado en _send_request: {e}", layer="ERROR")
                 self.disconnect(acquire_lock=False) # Forzar desconexión interna
                 # Envolver en una excepción genérica Modbus si no es ya una
                 raise ModbusException(f"Error inesperado procesando solicitud/respuesta: {e}") from e


    def _recv_all(self, num_bytes):
        """Lee exactamente num_bytes del socket, manejando lecturas parciales."""
        # Asegurarse de que el socket exista y tenga timeout
        if not self.sock:
            raise ConnectionException("Socket no disponible para recv.")
        # self.sock.settimeout(valor_timeout) # Asegurarse de que el timeout esté seteado

        data = bytearray()
        while len(data) < num_bytes:
            packet = self.sock.recv(num_bytes - len(data))
            if not packet:
                # Conexión cerrada por el otro extremo inesperadamente
                self._log("ERROR", f"Conexión cerrada por el peer mientras se esperaban {num_bytes} bytes (recibidos {len(data)}).", layer="SOCKET")
                self.disconnect(acquire_lock=False) # Forzar desconexión interna
                raise ConnectionException("Conexión cerrada inesperadamente por el servidor.")
            data.extend(packet)
        return bytes(data)


    def read_holding_registers(self, unit_id, starting_address, quantity):
        """Lee registros Holding (Función 0x03). Síncrono."""
        if not (0 <= starting_address <= 65535):
            raise ValueError("Dirección inicial fuera de rango (0-65535)")
        if not (1 <= quantity <= 125):
             raise ValueError("Cantidad de registros fuera de rango (1-125)")

        function_code = 0x03
        request = self._build_modbus_frame(unit_id, function_code, starting_address, quantity)

        # _send_request ya está protegido por lock y maneja errores de conexión/timeout
        rx_unit_id, response_pdu = self._send_request(request)

        # Validar Unit ID (aunque en TCP/IP esto es menos crítico que el TID, es bueno chequear)
        if rx_unit_id != unit_id:
            self._log("WARN", f"Unit ID no coincide en respuesta. Esperado: {unit_id}, Recibido: {rx_unit_id}", layer="MB_ERROR")
            # Podríamos lanzar excepción o continuar si no es crítico para la aplicación
            # raise ModbusInvalidResponseException(f"Unit ID no coincide. Esperado: {unit_id}, Recibido: {rx_unit_id}")

        # Analizar PDU
        rx_func_code = response_pdu[0]

        if rx_func_code == (function_code | 0x80):
            if len(response_pdu) < 2:
                 raise ModbusInvalidResponseException("Respuesta de error Modbus incompleta (falta código de excepción).")
            error_code = response_pdu[1]
            self._log("ERROR", f"Respuesta de error Modbus recibida. Código: {error_code}", layer="MB_ERROR")
            raise ModbusIOException(f"Error Modbus recibido del dispositivo. Código: {error_code}", error_code=error_code)
        elif rx_func_code != function_code:
            raise ModbusInvalidResponseException(f"Código de función incorrecto en respuesta. Esperado: {function_code}, Recibido: {rx_func_code}")

        # Procesar respuesta normal
        if len(response_pdu) < 2:
             raise ModbusInvalidResponseException("Respuesta PDU demasiado corta para contener byte count.")
        byte_count = response_pdu[1]
        data_bytes = response_pdu[2:]

        if byte_count != len(data_bytes):
            raise ModbusInvalidResponseException(f"Byte count ({byte_count}) no coincide con longitud de datos ({len(data_bytes)}).")
        if byte_count != quantity * 2:
             raise ModbusInvalidResponseException(f"Byte count ({byte_count}) no coincide con cantidad solicitada ({quantity}*2 bytes).")

        values = DataFormatter.parse_registers(data_bytes, quantity)
        self._log("DEBUG", f"Registros leídos exitosamente ({quantity} regs desde {starting_address}): {values}", layer="MODBUS")
        return values

    # --- Otros métodos Modbus (read_coils, write_register, etc.) seguirían un patrón similar ---

