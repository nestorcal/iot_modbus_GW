# IOT Modbus Gateway

## Introducción


```
modbus-web-app/
├── app.py                 # Archivo principal de Flask (Controladores/Rutas)
├── requirements.txt       # Dependencias de Python
├── .gitignore             # Archivos a ignorar por Git
│
├── modbus_client/         # Lógica del cliente Modbus
│   ├── __init__.py
│   ├── client.py          # Clase ModbusTCPClient (adaptada)
│   ├── exceptions.py      # Excepciones personalizadas
│   └── formatter.py       # Utilidades para formatear datos
│
├── services/              # Lógica de negocio y coordinación
│   ├── __init__.py
│   └── modbus_service.py  # Servicio para manejar el cliente y datos
│
├── templates/             # Plantillas HTML (Frontend)
│   └── index.html
│
└── static/                # Archivos estáticos (CSS, JS)
    ├── js/
    │   └── main.js        # Lógica JavaScript del frontend
    └── css/
        └── style.css      # Estilos (opcional, básico)
```




