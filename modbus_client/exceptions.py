class ModbusException(Exception):
    """Clase base para excepciones Modbus."""
    pass

class ConnectionException(ModbusException):
    """Error al conectar/comunicar a nivel de socket."""
    pass

class ModbusIOException(ModbusException):
    """Error en la respuesta Modbus (ej. función no soportada, dirección inválida)."""
    def __init__(self, message, error_code=None):
        super().__init__(message)
        self.error_code = error_code

class ModbusInvalidResponseException(ModbusException):
    """La respuesta recibida no cumple el formato esperado."""
    pass