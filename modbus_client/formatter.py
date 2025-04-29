import struct

class DataFormatter:
    @staticmethod
    def format_value(value, format_type='dec'):
        """Formatea un valor de registro según el tipo especificado."""
        if format_type == 'hex':
            return f"0x{value:04X}"
        elif format_type == 'bin':
             return f"0b{value:016b}"
        # Añadir más formatos aquí (float, etc.) si es necesario
        else: # 'dec' por defecto
            return str(value)

    @staticmethod
    def parse_registers(data_bytes, quantity):
        """Parsea bytes recibidos en una lista de registros (words/16 bits)."""
        if len(data_bytes) != quantity * 2:
            raise ModbusInvalidResponseException(f"Tamaño de datos incorrecto. Esperado {quantity*2} bytes, recibidos {len(data_bytes)}")

        values = []
        for i in range(0, len(data_bytes), 2):
            # '>H' significa Big-Endian Unsigned Short (16 bits)
            value = struct.unpack('>H', data_bytes[i:i+2])[0]
            values.append(value)
        return values