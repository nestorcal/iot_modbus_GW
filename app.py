# app.py
from flask import Flask, render_template, request, jsonify
import signal
import sys
import threading
import os

# --- Importar Servicios y Utilidades ---
from services.log_service import LogService
from services.register_service import RegisterService
from services.connection_service import ConnectionService, ServiceError
from services.polling_service import PollingService # Importar PollingService
from modbus_client.formatter import DataFormatter

# --- Configuración de la Aplicación Flask ---
app = Flask(__name__)

# --- Inicialización Singleton de Servicios ---
log_service = LogService()
register_service = RegisterService(log_service=log_service)
# PollingService necesita ser creado ANTES que ConnectionService si este último lo va a llamar
polling_service = PollingService(log_service=log_service,
                                 # Pasar Nones temporalmente, se setearán después
                                 connection_service=None,
                                 register_service=register_service)
connection_service = ConnectionService(log_service=log_service,
                                       register_service=register_service,
                                       polling_service=polling_service) # Pasar polling al connection service
# Ahora que connection_service existe, inyectarlo en polling_service
polling_service.connection_service = connection_service


# --- Rutas de la API REST y Vistas HTML ---

@app.route('/')
def index():
    """Sirve la página principal."""
    log_service.log_debug("Solicitud GET a '/'")
    initial_status = connection_service.get_connection_status()
    initial_registers = register_service.get_register_data()
    return render_template('index.html',
                           initial_status=initial_status,
                           initial_registers=initial_registers)

# --- Rutas Connect/Disconnect (sin cambios) ---
@app.route('/api/connect', methods=['POST'])
def connect_modbus():
    log_service.log_info("POST /api/connect"); response_data = {"success": False, "message": "Error"}; status_code = 500
    try:
        data = request.get_json(); ip = data.get('ip'); port = data.get('port'); unit_id = data.get('unit_id'); mode = data.get('mode', 'tcp')
        log_service.log_debug(f"Connect Data: {ip}:{port} U:{unit_id} M:{mode}")
        if not ip or not port or unit_id is None: raise ValueError("Faltan parámetros.")
        if mode not in ['tcp', 'rtu_over_tcp']: raise ValueError(f"Modo '{mode}' inválido.")
        result_dict = connection_service.connect(ip, port, unit_id, mode) # Devuelve dict
        response_data = result_dict; status_code = 200
    except ValueError as ve: log_service.log_warning(f"Validation Error: {ve}"); response_data = {"success": False, "message": str(ve)}; status_code = 400
    except ServiceError as se: log_service.log_error(f"Service Error: {se}"); response_data = {"success": False, "message": f"Error Servicio: {se}"}; status_code = 500
    except Exception as e: log_service.log_critical(f"Unexpected Error /api/connect: {e}", exc_info=True); response_data = {"success": False, "message": "Error Interno Servidor."}
    finally: return jsonify(response_data), status_code

@app.route('/api/disconnect', methods=['POST'])
def disconnect_modbus():
    log_service.log_info("POST /api/disconnect"); response_data = {"success": False, "message": "Error"}; status_code = 500
    try:
        log_service.log_info("Deteniendo Polling Service (si aplica)..."); polling_service.stop_polling() # Stop ya no hace nada si no corre
        log_service.log_info("Llamando a ConnectionService.disconnect..."); result_dict = connection_service.disconnect() # Devuelve dict
        response_data = result_dict; status_code = 200
    except ServiceError as se: log_service.log_error(f"Service Error /disconnect: {se}"); response_data = {"success": False, "message": f"Error Servicio: {se}"}; status_code = 500
    except Exception as e: log_service.log_critical(f"Error inesperado /disconnect: {e}", exc_info=True); response_data = {"success": False, "message": "Error Interno Servidor."}
    finally: return jsonify(response_data), status_code

# --- Ruta Status (sin cambios) ---
@app.route('/api/status', methods=['GET'])
def get_status():
    try: status = connection_service.get_connection_status(); return jsonify(status)
    except Exception as e: log_service.log_error(f"Error /api/status: {e}", exc_info=True); return jsonify({"connected": False, "is_connecting": False, "message": "Error estado", "last_error": "Error servidor"}), 500

# --- Ruta Registers (sin cambios) ---
@app.route('/api/registers', methods=['GET'])
def get_registers():
    format_type = request.args.get('format', 'dec'); response_data = {"error": "Error interno"}
    try:
        register_data = register_service.get_register_data()
        formatted_values = [DataFormatter.format_value(v, format_type) for v in register_data.get("values", [])]
        response_data = {"start_addr": register_data.get("start_addr"), "count": register_data.get("count"), "values": formatted_values, "raw_values": register_data.get("values", []), "last_update": register_data.get("last_update"), "format": format_type}
        return jsonify(response_data)
    except Exception as e: log_service.log_error(f"Error /api/registers: {e}", exc_info=True); return jsonify(response_data), 500

# --- Ruta Debug Log (sin cambios) ---
@app.route('/api/debuglog', methods=['GET'])
def get_debug_log():
    try: logs = log_service.get_logs(); return jsonify({"logs": logs})
    except Exception as e: log_service.log_error(f"Error /api/debuglog: {e}", exc_info=True); return jsonify({"logs": [f"ERROR LOGS: {e}"]}), 500

# --- Ruta Update Params (sin cambios) ---
@app.route('/api/update_params', methods=['POST'])
def update_params():
    log_service.log_info("POST /api/update_params")
    try:
        data = request.get_json();
        if not data: return jsonify({"success": False, "message": "Falta JSON."}), 400
        start_addr = data.get('start_addr'); count = data.get('count')
        if start_addr is None or count is None: return jsonify({"success": False, "message": "Faltan params."}), 400
        result = register_service.update_read_parameters(start_addr, count)
        return jsonify(result)
    except Exception as e: log_service.log_critical(f"Error /api/update_params: {e}", exc_info=True); return jsonify({"success": False, "message": "Error servidor."}), 500

# --- <<< NUEVA RUTA para Lectura Bajo Demanda >>> ---
@app.route('/api/readnow', methods=['POST'])
def read_registers_now():
    """Endpoint API para disparar una lectura única de registros."""
    log_service.log_info("Solicitud POST a /api/readnow")
    try:
        # Llamar al método read_once del PollingService
        result = polling_service.read_once()
        # Devolver el resultado (que ya es un diccionario)
        # El código de estado será 200 OK si la llamada al servicio no falló,
        # el 'success' dentro del JSON indica si la LECTURA fue exitosa.
        return jsonify(result), 200
    except Exception as e:
        log_service.log_critical(f"Error inesperado en la ruta /api/readnow: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Error interno del servidor al intentar leer."}), 500

# --- Ruta Intervalo (sin cambios) ---
@app.route('/api/polling/interval', methods=['POST'])
def set_polling_interval():
     log_service.log_info("POST /api/polling/interval")
     try:
        data = request.get_json();
        if not data: return jsonify({"success": False, "message": "Falta JSON."}), 400
        interval = data.get('interval')
        if interval is None: return jsonify({"success": False, "message": "Falta 'interval'."}), 400
        # Esto ahora no tendría efecto si el polling automático está deshabilitado
        # success = polling_service.set_interval(interval)
        success = False # Marcar como no soportado por ahora
        message = "Configuración de intervalo automático no soportada en modo lectura única." # Mensaje claro
        # message = f"Intervalo actualizado a {interval}s." if success else f"Intervalo inválido: {interval}."
        return jsonify({"success": success, "message": message})
     except Exception as e: log_service.log_error(f"Error /api/polling/interval: {e}", exc_info=True); return jsonify({"success": False, "message": "Error interno."}), 500

# --- Manejo de Cierre Limpio (sin cambios) ---
def handle_shutdown_signal(signum, frame):
    print("\nApagando..."); log_service.log_info("Señal apagado...")
    # polling_service.stop_polling() # Ya no es necesario
    print("Desconectando..."); log_service.log_info("Desconectando...")
    connection_service.disconnect()
    log_service.log_info("Saliendo."); print("Saliendo.")
    sys.exit(0)
signal.signal(signal.SIGINT, handle_shutdown_signal); signal.signal(signal.SIGTERM, handle_shutdown_signal)

# --- Punto de Entrada ---
if __name__ == '__main__':
    log_service.log_info(f"***** Iniciando Servidor (PID: {os.getpid()}) *****")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False, threaded=True)



