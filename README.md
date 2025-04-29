# IoT Modbus GW

![Versión de Python](https://img.shields.io/badge/python-3.8-blue.svg)
![Licencia](https://img.shields.io/badge/license-BSD-green.svg)

Aplicación web simple basada en Flask que actúa como cliente Modbus, permitiendo conectar a dispositivos Modbus TCP o Modbus RTU over TCP a través de la red, leer registros (Holding Registers inicialmente) y visualizar la comunicación y el estado en tiempo real.

## Características

*   **Modos de Conexión:** Soporta conexiones a dispositivos:
    *   Modbus TCP (usando cabecera MBAP)
    *   Modbus RTU over TCP (frame RTU con CRC16 sobre socket TCP)
*   **Configuración Flexible:** Permite configurar IP, Puerto, Unit ID (Slave ID) y Modo de conexión.
*   **Lectura de Registros:**
    *   Implementado actualmente para Holding Registers (código 0x03).
    *   Lectura inicial automática al conectar.
    *   Lectura bajo demanda mediante botón.
    *   Permite configurar dirección de inicio (offset base 0) y cantidad.
    *   Visualización de valores en Decimal, Hexadecimal y Binario.
*   **Estado en Tiempo Real:** Muestra el estado actual (Desconectado, Conectando, Conectado, Error) y mensajes relevantes.
*   **Monitor de Conexión:**
    *   Muestra el tiempo de actividad de la conexión.
    *   Implementa reintentos de conexión con feedback visual.
    *   Proceso de conexión asíncrono (no bloquea la interfaz).
    *   Mecanismo básico de Keep-Alive para mantener la conexión TCP activa.
*   **Visor de Debug:** Panel desplegable que muestra logs detallados del backend, incluyendo:
    *   Información de conexión/desconexión.
    *   Intentos de conexión.
    *   Logs del cliente Modbus (incluyendo frames enviados/recibidos a nivel DEBUG).
    *   Errores de comunicación o del servicio.

## Estructura del Proyecto

```text
modbus-web-app/
├── app.py                 # Archivo principal Flask (Rutas API, Vistas)
├── requirements.txt       # Dependencias Python
├── .gitignore             # Archivos/Carpetas ignorados por Git
│
├── modbus_client/         # Clases cliente para protocolos Modbus
│   ├── __init__.py
│   ├── tcp_client.py      # Cliente para Modbus TCP (MBAP)
│   ├── rtu_over_tcp_client.py # Cliente para Modbus RTU sobre TCP
│   ├── exceptions.py      # Excepciones Modbus personalizadas
│   └── formatter.py       # Utilidades para formatear datos
│
├── services/              # Capa de servicios (Lógica de negocio)
│   ├── __init__.py
│   ├── log_service.py     # Servicio para manejar logs
│   ├── register_service.py # Servicio para manejar datos y parámetros de registros
│   ├── connection_service.py # Servicio para gestionar la conexión (estado, cliente, hilos)
│   └── polling_service.py # Servicio para realizar lecturas bajo demanda
│
├── templates/             # Plantillas HTML (Interfaz de usuario)
│   └── index.html
│
└── static/                # Archivos estáticos (CSS, JS)
    ├── js/
    │   └── main.js        # Lógica JavaScript del frontend
    └── css/
        └── style.css      # Hoja de estilos CSS
```
# Instalación

## Prerrequisitos

- Python 3.8 o superior
- pip (incluido con Python)
- Git (opcional, para clonar el repositorio)

## Configuración del Entorno

### Clonar el repositorio (opcional):
```bash
git clone https://github.com/tu-repositorio/modbus-web-app.git
cd modbus-web-app
```

### Crear y activar entorno virtual:
```bash
python -m venv venv

# Windows:
.\venv\Scripts\activate

```

### Instalar dependencias:
```bash
pip install -r requirements.txt
```

# Uso

## Iniciar la aplicación:
```bash
python app.py
```
El servidor se iniciará por defecto en [http://0.0.0.0:5000](http://0.0.0.0:5000)

> **Nota:** Para entornos de producción, se recomienda usar un servidor WSGI como Gunicorn o Waitress.

## Acceder a la interfaz web:

- Abre tu navegador en [http://localhost:5000](http://localhost:5000)
- Para acceso remoto: `http://<IP_DEL_SERVIDOR>:5000`

## Configurar conexión:

- Seleccionar modo (TCP o RTU over TCP)
- Introducir IP del dispositivo Modbus
- Especificar puerto TCP
- Indicar Unit ID/Slave ID
- Hacer clic en **"Conectar"**

## Leer registros:

- La lectura inicial automática usa offset 0 y 10 registros
- Modificar parámetros según necesidad:
  - Offset de inicio
  - Cantidad de registros
- Hacer clic en **"Actualizar Parámetros"** para guardar cambios
- Usar **"Leer Registros Ahora"** para nueva lectura

# Roadmap

## Próximas Funcionalidades

- Soporte para otros tipos de registros:
  - Coils (0x01)
  - Discrete Inputs (0x02)
  - Input Registers (0x04)

- Operaciones de escritura:
  - Write Single Register (0x06)
  - Write Multiple Registers (0x10)
  - Write Single Coil (0x05)
  - Write Multiple Coils (0x0F)

- Mejoras en manejo de errores:
  - Interpretación de códigos de excepción Modbus
  - Reintentos inteligentes
  - Notificaciones detalladas

## Mejoras Planeadas

- Autenticación de usuarios
- Histórico de conexiones
- Exportación de datos (CSV, JSON)
- API REST para integración con otros sistemas
- Soporte para múltiples conexiones simultáneas

