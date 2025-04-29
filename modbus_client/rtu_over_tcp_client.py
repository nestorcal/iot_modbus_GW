import socket
import struct
import time
import threading
import crcmod.predefined # Para calcular CRC

from .exceptions import ConnectionException, ModbusIOException, ModbusInvalidResponseException
from .formatter import DataFormatter

# Función CRC Modbus (RTU)
crc16_func = crcmod.predefined.mkPredefinedCrcFun('modbus')

class ModbusRtuOverTcpClient:
    """
    Cliente Modbus que envía frames RTU (con CRC) sobre una conexión TCP.
    """
    def __init__(self):
        self.ip = None
        self.port = None
        self.sock = None
        # transaction_id no se usa en RTU framing
        self.is_connected = False
        self.connection_start_time = None
        self._log_service = None
        self._client_lock = threading.Lock() # Lock para operaciones del socket
        self.timeout = 5 # Timeout por defecto para operaciones de socket

    def set_log_service(self, log_service):
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

    def connect(self, ip, port, timeout=5):
        """Establece conexión TCP (síncrona). Lanza excepción en fallo."""
        with self._client_lock:
            if self.is_connected:
                 raise ConnectionException("Cliente RTU over TCP ya está conectado.")

            self.ip = ip
            self.port = port
            self.timeout = timeout # Guardar timeout

            self._log("INFO", f"Intentando conectar (RTU over TCP) a {self.ip}:{self.port} (Timeout: {self.timeout}s)...", layer="SOCKET")
            temp_sock = None
            try:
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(self.timeout)
                temp_sock.connect((self.ip, self.port))

                self.sock = temp_sock
                self.is_connected = True
                self.connection_start_time = time.time()
                self._log("INFO", f"Conexión TCP establecida para RTU over TCP con {self.ip}:{self.port}", layer="SOCKET")

            except socket.timeout:
                self._log("ERROR", f"Timeout ({self.timeout}s) al conectar a {self.ip}:{self.port}", layer="SOCKET")
                if temp_sock: temp_sock.close()
                self._reset_connection_state()
                raise ConnectionException(f"Timeout al conectar a {self.ip}:{self.port}")
            except Exception as e:
                self._log("ERROR", f"Error de conexión a {self.ip}:{self.port}: {e}", layer="SOCKET")
                if temp_sock: temp_sock.close()
                self._reset_connection_state()
                raise ConnectionException(f"Error de conexión: {e}")

    def _reset_connection_state(self):
        """ Método auxiliar para limpiar el estado de conexión """
        self.sock = None
        self.is_connected = False
        self.connection_start_time = None

    def disconnect(self, acquire_lock=True):
        """Cierra la conexión del socket."""
        lock = self._client_lock if acquire_lock else None
        if lock: lock.acquire()
        try:
            if self.sock:
                self._log("INFO", "Cerrando socket (RTU over TCP)...", layer="SOCKET")
                try:
                    self.sock.close()
                    self._log("INFO", "Socket cerrado.", layer="SOCKET")
                except Exception as e:
                    self._log("ERROR", f"Error al cerrar socket: {e}", layer="SOCKET")
                finally:
                    self._reset_connection_state()
            else:
                self._reset_connection_state() # Asegurar estado limpio
        finally:
            if lock: lock.release()

    def get_connection_uptime(self):
        if self.is_connected and self.connection_start_time:
            return time.time() - self.connection_start_time
        return 0

    def _build_rtu_frame(self, slave_id, function_code, starting_address, quantity):
        """Construye el PDU Modbus y le añade SlaveID y CRC16."""
        # PDU (Protocol Data Unit) para Read Holding Registers (0x03)
        pdu = struct.pack('>BHH', function_code, starting_address, quantity)
        # Frame RTU sin CRC: SlaveID + PDU
        frame_no_crc = struct.pack('>B', slave_id) + pdu
        # Calcular CRC16
        crc = crc16_func(frame_no_crc)
        # Frame completo: SlaveID + PDU + CRC16 (Little-Endian)
        rtu_frame = frame_no_crc + struct.pack('<H', crc) # '<H' es unsigned short little-endian
        self._log("DEBUG", f"Frame RTU construido (Slave: {slave_id}): {rtu_frame.hex()}", layer="RTU_SENT")
        return rtu_frame

    def _recv_all(self, num_bytes):
        """Lee exactamente num_bytes del socket."""
        if not self.sock: raise ConnectionException("Socket no disponible para recv.")
        self.sock.settimeout(self.timeout) # Asegurar timeout para cada lectura
        data = bytearray()
        start_recv_time = time.monotonic()
        while len(data) < num_bytes:
             time_elapsed = time.monotonic() - start_recv_time
             if time_elapsed > self.timeout:
                  self._log("ERROR", f"Timeout parcial al leer {num_bytes} bytes (recibidos {len(data)}).", layer="SOCKET")
                  self.disconnect(acquire_lock=False)
                  raise socket.timeout(f"Timeout parcial esperando datos (recibidos {len(data)}/{num_bytes})")

             remaining_timeout = self.timeout - time_elapsed
             self.sock.settimeout(remaining_timeout) # Ajustar timeout restante

             try:
                 packet = self.sock.recv(num_bytes - len(data))
                 if not packet:
                     self._log("ERROR", f"Conexión cerrada por peer mientras se esperaban {num_bytes} bytes (recibidos {len(data)}).", layer="SOCKET")
                     self.disconnect(acquire_lock=False)
                     raise ConnectionException("Conexión cerrada inesperadamente por el servidor.")
                 data.extend(packet)
             except socket.timeout: # Timeout específico de esta llamada recv
                 self._log("ERROR", f"Timeout final al esperar el resto de {num_bytes} bytes (recibidos {len(data)}).", layer="SOCKET")
                 self.disconnect(acquire_lock=False)
                 raise socket.timeout(f"Timeout final esperando datos (recibidos {len(data)}/{num_bytes})")
             except Exception as e:
                  self._log("ERROR", f"Error inesperado durante recv: {e}", layer="SOCKET")
                  self.disconnect(acquire_lock=False)
                  raise ConnectionException(f"Error de socket durante recv: {e}")

        return bytes(data)


    def _verify_crc(self, frame_with_crc):
        """Verifica el CRC16 de un frame RTU recibido."""
        if len(frame_with_crc) < 3: # Mínimo: SlaveID+FuncCode+CRC(2) o SlaveID+ErrCode+ExCode+CRC(2)
            return False
        data_part = frame_with_crc[:-2]
        received_crc_bytes = frame_with_crc[-2:]
        received_crc = struct.unpack('<H', received_crc_bytes)[0] # Little-Endian
        calculated_crc = crc16_func(data_part)
        if received_crc != calculated_crc:
             self._log("ERROR", f"CRC ERROR! Recibido: 0x{received_crc:04X}, Calculado: 0x{calculated_crc:04X} para datos: {data_part.hex()}", layer="RTU_ERROR")
             return False
        # self._log("DEBUG", f"CRC OK (0x{received_crc:04X}) para datos: {data_part.hex()}", layer="RTU_RECV")
        return True

    def _send_request_rtu(self, request_rtu_frame, expected_response_len_func):
        """
        Envía un frame RTU y maneja la recepción de la respuesta
        basándose en la longitud esperada o detectando errores.
        `expected_response_len_func` es una función que, dado el inicio de la
        respuesta (slave_id, func_code), devuelve cuántos bytes *adicionales* leer.
        """
        with self._client_lock:
            if not self.is_connected or not self.sock:
                raise ConnectionException("No conectado al servidor Modbus.")

            try:
                self._log("DEBUG", f"Enviando frame RTU ({len(request_rtu_frame)} bytes): {request_rtu_frame.hex()}", layer="TCP")
                self.sock.sendall(request_rtu_frame)

                # Leer inicio de respuesta (SlaveID + Function Code)
                self._log("DEBUG", "Esperando inicio de respuesta RTU (2 bytes)...", layer="RTU_RECV")
                initial_bytes = self._recv_all(2) # Slave ID (1) + Func Code (1)
                rx_slave_id, rx_func_code = struct.unpack('>BB', initial_bytes)
                self._log("DEBUG", f"Recibido inicio RTU: SlaveID={rx_slave_id}, FuncCode=0x{rx_func_code:02X}", layer="RTU_RECV")

                # Determinar si es una respuesta de error
                is_error = (rx_func_code & 0x80) != 0
                bytes_to_read_more = 0

                if is_error:
                    # Error: Leer Exception Code (1 byte) + CRC (2 bytes) = 3 bytes más
                    bytes_to_read_more = 1 + 2
                    self._log("DEBUG", f"Respuesta de error detectada. Esperando {bytes_to_read_more} bytes más (ExCode + CRC)...", layer="RTU_RECV")
                else:
                    # Respuesta normal: usar la función para determinar longitud restante
                    bytes_to_read_more = expected_response_len_func(rx_slave_id, rx_func_code)
                    if bytes_to_read_more < 2: # Debe incluir al menos el CRC
                         raise ModbusInvalidResponseException(f"Función de longitud esperada devolvió un valor inválido ({bytes_to_read_more}). Debe ser >= 2.")
                    self._log("DEBUG", f"Respuesta normal. Esperando {bytes_to_read_more} bytes más (Datos + CRC)...", layer="RTU_RECV")

                # Leer el resto de la respuesta
                remaining_bytes = self._recv_all(bytes_to_read_more)
                full_response_frame = initial_bytes + remaining_bytes
                self._log("DEBUG", f"Frame RTU completo recibido ({len(full_response_frame)} bytes): {full_response_frame.hex()}", layer="RTU_RECV")

                # Verificar CRC
                if not self._verify_crc(full_response_frame):
                     raise ModbusInvalidResponseException("Fallo de verificación CRC en la respuesta.")

                # Extraer PDU (quitar SlaveID y CRC)
                pdu_bytes = full_response_frame[1:-2] # Índice 1 hasta 2 antes del final

                return rx_slave_id, pdu_bytes # Devolver PDU para procesamiento

            except socket.timeout as e:
                self._log("ERROR", f"Timeout durante send/recv RTU: {e}", layer="SOCKET")
                # disconnect ya se llama dentro de _recv_all en caso de timeout
                raise ConnectionException(f"Timeout en comunicación Modbus RTU over TCP: {e}") from e
            except (ConnectionException, ModbusException) as e:
                 # Errores ya logueados y desconectados internamente si es necesario
                 raise e # Re-lanzar
            except Exception as e:
                 self._log("CRITICAL", f"Error inesperado en _send_request_rtu: {e}", layer="ERROR")
                 self.disconnect(acquire_lock=False) # Forzar desconexión
                 raise ModbusException(f"Error inesperado procesando RTU over TCP: {e}") from e

    def read_holding_registers(self, unit_id, starting_address, quantity):
        """Lee registros Holding (Función 0x03) usando RTU over TCP."""
        if not (0 <= starting_address <= 65535): raise ValueError("Dirección inicial fuera de rango")
        if not (1 <= quantity <= 125): raise ValueError("Cantidad fuera de rango (1-125)")

        slave_id = unit_id
        function_code = 0x03
        request_frame = self._build_rtu_frame(slave_id, function_code, starting_address, quantity)

        def expected_len_func_03(rx_sid, rx_fcode):
            # Para respuesta 0x03 normal: ByteCount(1) + Data(N=ByteCount) + CRC(2)
            # Necesitamos leer el ByteCount primero para saber N.
            # Esta función devuelve los bytes *después* de SlaveID y FuncCode.
            # Así que necesitamos leer ByteCount (1 byte) + CRC (2 bytes) = 3 bytes MÍNIMO.
            # El resto depende del valor de ByteCount.
            # *** Estrategia: Leer ByteCount, luego calcular y leer Data+CRC ***

            # Leer ByteCount (1 byte)
            self._log("DEBUG", "Leyendo ByteCount (1 byte) para respuesta 0x03...", layer="RTU_RECV")
            byte_count_byte = self._recv_all(1)
            byte_count = struct.unpack('>B', byte_count_byte)[0]
            self._log("DEBUG", f"ByteCount = {byte_count}", layer="RTU_RECV")

            # Validar byte_count (debe ser quantity * 2)
            if byte_count != quantity * 2:
                 # Esto indica un problema grave de desincronización o error del esclavo
                 raise ModbusInvalidResponseException(f"Byte count en respuesta ({byte_count}) no coincide con cantidad solicitada ({quantity}*2 bytes).")

            # Bytes restantes = Data (byte_count) + CRC (2)
            bytes_to_read_next = byte_count + 2
            self._log("DEBUG", f"Esperando {bytes_to_read_next} bytes más (Data + CRC)...", layer="RTU_RECV")

            # DEVOLVEMOS EL NÚMERO DE BYTES A LEER *DESPUÉS* DEL BYTECOUNT
            # La función _send_request_rtu leerá estos bytes.
            # El frame completo será: SlaveID+FuncCode + ByteCountByte + DataBytes+CRCBytes
            return bytes_to_read_next

        # Modificar _send_request_rtu para manejar esta lectura en dos pasos
        # O, alternativamente, simplificar y leer todo de una vez si podemos predecir:
        # Longitud total esperada = 1 (SlaveID) + 1 (FuncCode) + 1 (ByteCount) + N (Data) + 2 (CRC)
        # donde N = quantity * 2. Longitud total = 5 + quantity * 2 bytes.

        def simpler_expected_len_func_03(rx_sid, rx_fcode):
            # Simplemente devuelve los bytes esperados después de SlaveID+FuncCode
            # Bytes = ByteCount(1) + Data(quantity*2) + CRC(2)
            return 1 + (quantity * 2) + 2

        # Usamos la función más simple para _send_request_rtu
        rx_slave_id, response_pdu = self._send_request_rtu(request_frame, simpler_expected_len_func_03)

        # Validar Slave ID recibido
        if rx_slave_id != slave_id:
            self._log("WARN", f"Slave ID no coincide en respuesta RTU. Esperado: {slave_id}, Recibido: {rx_slave_id}", layer="RTU_ERROR")
            # Podría ser crítico dependiendo de la red

        # Procesar el PDU (ya sin SlaveID ni CRC, y CRC verificado)
        rx_func_code = response_pdu[0] # Func code está al inicio del PDU

        # Chequear error Modbus (ya se hizo parcialmente al leer, pero doble check)
        if (rx_func_code & 0x80) != 0:
            if len(response_pdu) < 2: raise ModbusInvalidResponseException("PDU de error RTU incompleto.")
            error_code = response_pdu[1]
            self._log("ERROR", f"Respuesta de error Modbus RTU. Código: {error_code}", layer="RTU_ERROR")
            raise ModbusIOException(f"Error Modbus RTU recibido. Código: {error_code}", error_code=error_code)
        elif rx_func_code != function_code:
             raise ModbusInvalidResponseException(f"Código de función RTU incorrecto. Esperado: {function_code}, Recibido: {rx_func_code}")

        # Procesar PDU normal 0x03: ByteCount(1) + Data(N)
        if len(response_pdu) < 2: raise ModbusInvalidResponseException("PDU de respuesta 0x03 RTU incompleto.")
        byte_count = response_pdu[1]
        data_bytes = response_pdu[2:]

        if byte_count != len(data_bytes):
            raise ModbusInvalidResponseException(f"Byte count PDU ({byte_count}) no coincide con longitud datos PDU ({len(data_bytes)}).")
        if byte_count != quantity * 2:
             raise ModbusInvalidResponseException(f"Byte count PDU ({byte_count}) no coincide con cantidad solicitada ({quantity}*2 bytes).")

        values = DataFormatter.parse_registers(data_bytes, quantity)
        self._log("DEBUG", f"Registros leídos (RTU) ({quantity} regs desde {starting_address}): {values}", layer="MODBUS")
        return values

    # --- Métodos para otras funciones Modbus RTU (write, read coils, etc.) ---
    # Seguirían un patrón similar: construir frame RTU, definir función de longitud esperada,
    # llamar a _send_request_rtu, procesar PDU.

