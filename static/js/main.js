// static/js/main.js

/** Lógica principal del frontend */
document.addEventListener('DOMContentLoaded', () => {

    // --- Selección de Elementos DOM ---
    const connectBtn = document.getElementById('connect-btn');
    const disconnectBtn = document.getElementById('disconnect-btn');
    const updateParamsBtn = document.getElementById('update-params-btn');
    const readNowBtn = document.getElementById('read-now-btn');
    const toggleDebugBtn = document.getElementById('toggle-debug-btn');
    const modeSelect = document.getElementById('mode');
    const ipInput = document.getElementById('ip');
    const portInput = document.getElementById('port');
    const unitIdInput = document.getElementById('unit_id');
    const startAddrInput = document.getElementById('start_addr');
    const regCountInput = document.getElementById('reg_count');
    const formatSelect = document.getElementById('format-select');
    const connectionStatusSpan = document.getElementById('connection-status');
    const statusIndicator = document.getElementById('status-indicator');
    const connectionModeSpan = document.getElementById('connection-mode');
    const connectionUptimeSpan = document.getElementById('connection-uptime');
    const keepAliveStatusSpan = document.getElementById('keep-alive-status');
    const connectionMessageDiv = document.getElementById('connection-message');
    const registersTableBody = document.querySelector('#registers-table tbody');
    const lastUpdateTimeSpan = document.getElementById('last-update-time');
    const registersMessageDiv = document.getElementById('registers-message');
    const debugLogContainer = document.getElementById('debug-log-container');
    const debugLogPre = document.getElementById('debug-log');

    // --- Estado y Configuración ---
    let statusIntervalId = null;
    let debugIntervalId = null;
    let stopDebugTimeoutId = null;
    const STATUS_POLL_INTERVAL = 1000;
    const DEBUG_POLL_INTERVAL = 1500;
    const DEFAULT_PORT_TCP = 502;
    const DEFAULT_PORT_RTU = 2300;
    const DEBUG_STOP_DELAY = 2500;

    // --- Funciones de Utilidad ---
    function showMessage(element, message, isError = false, duration = 4000) { if (!element) return; element.textContent = message; element.className = isError ? 'message error-message' : 'message success-message'; if (duration > 0) { setTimeout(() => { if (element.textContent === message) { element.textContent = ''; element.className = 'message'; } }, duration); } }
    function formatUptime(totalSeconds) { if (!totalSeconds || totalSeconds < 1) return "0s"; const d=Math.floor(totalSeconds / 86400); const h=Math.floor((totalSeconds % 86400)/3600); const m=Math.floor((totalSeconds % 3600)/60); const s=Math.floor(totalSeconds % 60); let str=''; if(d>0)str+=`${d}d `; if(h>0||d>0)str+=`${h}h `; if(m>0||h>0||d>0)str+=`${m}m `; str+=`${s}s`; return str.trim(); }
    function formatKeepAliveStatus(timestamp) { if (timestamp === false) return "Keep-alive: FALLÓ"; if (!timestamp) return ""; const diff = Math.round((Date.now()-(timestamp*1000))/1000); return `Keep-alive OK (${diff}s atrás)`; }

    // --- Actualización UI (CORREGIDA lógica de inputs) ---
    function updateUIFromStatus(status) {
        if (!status) return;
        const isConnected = status.connected; const isConnecting = status.is_connecting; const currentMode = status.mode || 'tcp';

        // Estado General
        connectionStatusSpan.textContent = `Estado: ${status.message || 'Desconocido'}`;
        statusIndicator.className = isConnected?'connected':(status.last_error&&!isConnecting?'error':(isConnecting?'connecting':''));
        if (statusIndicator.className === '') statusIndicator.style.backgroundColor='grey'; else statusIndicator.style.backgroundColor='';
        connectionModeSpan.textContent = isConnected||isConnecting?`(${currentMode.toUpperCase()})`:'';
        connectionUptimeSpan.textContent = isConnected?`(Activo: ${formatUptime(status.uptime_seconds)})`:'';
        keepAliveStatusSpan.textContent = isConnected?formatKeepAliveStatus(status.last_keep_alive_ok):'';
        keepAliveStatusSpan.style.color = status.last_keep_alive_ok===false?'red':'#777';

        // Habilitar/Deshabilitar Controles
        const connectionInputsDisabled = isConnected || isConnecting;
        connectBtn.disabled = connectionInputsDisabled;
        disconnectBtn.disabled = !isConnected && !isConnecting;
        modeSelect.disabled = connectionInputsDisabled;
        ipInput.disabled = connectionInputsDisabled;
        portInput.disabled = connectionInputsDisabled;
        unitIdInput.disabled = connectionInputsDisabled;

        const registerControlsDisabled = !isConnected; // Habilitar solo si está conectado
        startAddrInput.disabled = registerControlsDisabled;
        regCountInput.disabled = registerControlsDisabled;
        formatSelect.disabled = registerControlsDisabled;
        updateParamsBtn.disabled = registerControlsDisabled;
        readNowBtn.disabled = registerControlsDisabled;

        // --- Rellenar Inputs (SOLO si está conectado/conectando) ---
        if (isConnected || isConnecting) {
            if (status.ip !== null && status.ip !== undefined && ipInput.value !== status.ip) ipInput.value = status.ip;
            if (status.port !== null && status.port !== undefined && portInput.value !== String(status.port)) portInput.value = status.port;
            if (status.unit_id !== null && status.unit_id !== undefined && unitIdInput.value !== String(status.unit_id)) unitIdInput.value = status.unit_id;
            if (status.mode !== null && status.mode !== undefined && modeSelect.value !== status.mode) modeSelect.value = status.mode;
        }
        // Si está desconectado, NO se tocan los inputs, permitiendo edición.

        // --- Tabla y Mensajes ---
        if (!isConnected && !isConnecting) {
            if (!status.last_error || connectionMessageDiv.textContent === '') { registersTableBody.innerHTML = '<tr><td colspan="2">Desconectado.</td></tr>'; lastUpdateTimeSpan.textContent = 'N/A'; }
        } else if (isConnected) {
            if (connectionMessageDiv.classList.contains('error-message')) { connectionMessageDiv.textContent = ''; connectionMessageDiv.className = 'message'; }
            // No iniciar polling de datos aquí, se hace con botón o al conectar
        }
        if (!isConnected && !isConnecting && status.last_error) { connectionMessageDiv.textContent = `Error: ${status.last_error}`; connectionMessageDiv.className = 'message error-message'; }
    }

    // --- Lógica API ---
    async function apiFetch(url, options = {}) { /* ... (igual) ... */ try { const r=await fetch(url,options); if(!r.ok){let m=`Error ${r.status}: ${r.statusText}`; try{m=(await r.json()).message||m;}catch(e){} throw new Error(m);} return r.status===204?null:await r.json(); } catch(e){console.error(`API Error (${options.method||'GET'} ${url}):`,e); throw e;} }
    async function fetchStatus() { try { const status = await apiFetch('/api/status'); updateUIFromStatus(status); } catch (e) { updateUIFromStatus({ connected: false, is_connecting: false, message: 'Error backend', last_error: e.message }); stopAllPolling(true); } }
    async function fetchDataAndUpdateUI() { // Lee y actualiza tabla
        const selectedFormat = formatSelect.value;
        registersMessageDiv.textContent = "Leyendo..."; registersMessageDiv.className = "message"; readNowBtn.disabled = true; // Deshabilitar botón mientras lee
        try {
            const result = await apiFetch('/api/readnow', { method: 'POST' }); // Llama a leer
            showMessage(registersMessageDiv, result.message, !result.success); // Muestra resultado
            if (result.success || result.data) { // Si lectura OK o devolvió datos (aunque sea [])
                // Pedir los datos formateados (RegisterService los tiene ahora)
                const data = await apiFetch(`/api/registers?format=${selectedFormat}`);
                if (!data) return;
                registersTableBody.innerHTML = ''; // Limpiar tabla
                if (data.values?.length > 0) {
                     const startAddr = data.start_addr; data.values.forEach((value, index) => {
                         const row = registersTableBody.insertRow(); row.insertCell().textContent = `${startAddr + index} (0x${(startAddr + index).toString(16).toUpperCase()})`;
                         const cellVal = row.insertCell(); cellVal.textContent = value;
                         if (data.raw_values?.[index] !== undefined) cellVal.dataset.rawValue = data.raw_values[index]; });
                 } else if (data.count > 0) { registersTableBody.innerHTML = `<tr><td colspan="2">Lectura OK, 0 valores recibidos.</td></tr>`; }
                 else { registersTableBody.innerHTML = `<tr><td colspan="2">Cantidad a leer es 0.</td></tr>`; }
                 lastUpdateTimeSpan.textContent = data.last_update ? new Date(data.last_update * 1000).toLocaleTimeString() : 'Ahora';
            }
        } catch (error) { showMessage(registersMessageDiv, `Error lectura: ${error.message}`, true); }
        finally { readNowBtn.disabled = false; } // Rehabilitar botón
    }
    async function fetchDebugLog() { /* ... (igual) ... */ if(debugLogContainer.classList.contains('hidden')) return; try { const d=await apiFetch('/api/debuglog'); if (!d?.logs) return; const st=debugLogPre.scrollTop; const sb=debugLogPre.scrollHeight-debugLogPre.clientHeight<=st+1; debugLogPre.textContent=d.logs.join('\n'); if(sb)debugLogPre.scrollTop=debugLogPre.scrollHeight; } catch(e){debugLogPre.textContent+=`\n--- Error logs: ${e.message} ---`;} }

    // --- Gestión Polling (Solo Status y Debug) ---
    function startStatusPolling() { if (statusIntervalId) clearInterval(statusIntervalId); fetchStatus(); statusIntervalId = setInterval(fetchStatus, STATUS_POLL_INTERVAL); console.debug("Status polling started."); }
    function stopStatusPolling() { if (statusIntervalId) { clearInterval(statusIntervalId); statusIntervalId = null; console.debug("Status polling stopped."); } }
    function startDebugPollingIfNeeded() { if (stopDebugTimeoutId) { clearTimeout(stopDebugTimeoutId); stopDebugTimeoutId = null; console.debug("Debug stop timeout cancelled."); } if (debugIntervalId) return; if (!debugLogContainer.classList.contains('hidden') && (statusIntervalId || !disconnectBtn.disabled)) { fetchDebugLog(); debugIntervalId = setInterval(fetchDebugLog, DEBUG_POLL_INTERVAL); console.debug("Debug polling started."); } else { console.debug("Debug polling NOT started."); } }
    function stopDebugPolling(immediate = false) { if (stopDebugTimeoutId) { clearTimeout(stopDebugTimeoutId); stopDebugTimeoutId = null; } if (!immediate && debugIntervalId) { console.debug(`Scheduling debug stop in ${DEBUG_STOP_DELAY}ms`); stopDebugTimeoutId = setTimeout(() => { if (debugIntervalId) { clearInterval(debugIntervalId); debugIntervalId = null; console.debug("Debug polling stopped (delayed)."); } stopDebugTimeoutId = null; }, DEBUG_STOP_DELAY); } else { if (debugIntervalId) { clearInterval(debugIntervalId); debugIntervalId = null; console.debug("Debug polling stopped (immediate)."); } } }
    function stopAllPolling(stopDebugImmediate = false) { stopStatusPolling(); stopDebugPolling(stopDebugImmediate); console.debug("All polling stop requested."); }

    // --- Manejadores de Eventos ---
    async function handleConnectClick() { /* ... (igual) ... */ const ip=ipInput.value.trim(); const port=portInput.value.trim(); const unit_id=unitIdInput.value.trim(); const mode=modeSelect.value; if(!ip||!port||unit_id===''){showMessage(connectionMessageDiv,'IP, Puerto y Unit ID requeridos.',true); return;} updateUIFromStatus({connected:false, is_connecting:true, message:'Iniciando conexión...', last_error:null, mode:mode}); startStatusPolling(); startDebugPollingIfNeeded(); try { const result = await apiFetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip,port,unit_id,mode}),}); showMessage(connectionMessageDiv, result.message, !result.success); /* La lectura inicial la dispara el monitor */ } catch(error){ showMessage(connectionMessageDiv,`Error: ${error.message}`,true,8000); updateUIFromStatus({connected:false,is_connecting:false,message:'Error crítico al conectar',last_error:error.message}); stopAllPolling(true);} }
    async function handleDisconnectClick() { /* ... (igual, usa stopDebugPolling(false)) ... */ updateUIFromStatus({connected:false,is_connecting:false,message:'Desconectando...'}); stopStatusPolling(); stopDebugPolling(false); try { const result=await apiFetch('/api/disconnect',{method:'POST'}); showMessage(connectionMessageDiv,result.message,!result.success); } catch(error){showMessage(connectionMessageDiv,`Error: ${error.message}`,true);} finally { setTimeout(async ()=>{await fetchStatus();}, DEBUG_STOP_DELAY + 500); } }
    async function handleUpdateParamsClick() { // Solo actualiza params
        const status = await apiFetch('/api/status').catch(() => ({connected: false})); if (!status?.connected) { showMessage(registersMessageDiv, 'Debe estar conectado.', true); return; }
        const start_addr = startAddrInput.value; const count = regCountInput.value;
        registersMessageDiv.textContent = "Actualizando parámetros..."; registersMessageDiv.className = "message"; updateParamsBtn.disabled = true; // Deshabilitar mientras actualiza
        try { const result=await apiFetch('/api/update_params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_addr,count}),}); showMessage(registersMessageDiv, result.message, !result.success); }
        catch (error){ showMessage(registersMessageDiv,`Error: ${error.message}`,true); }
        finally { updateParamsBtn.disabled = false; } // Rehabilitar
    }
    async function handleReadNowClick() { // Llama a leer y actualizar UI
        await fetchDataAndUpdateUI();
    }
    function handleToggleDebugClick() { debugLogContainer.classList.toggle('hidden'); toggleDebugBtn.textContent = debugLogContainer.classList.contains('hidden') ? 'Mostrar' : 'Ocultar'; if (!debugLogContainer.classList.contains('hidden')) { startDebugPollingIfNeeded(); } else { stopDebugPolling(true); } }
    function handleModeChange() { const mode = modeSelect.value; portInput.value = mode === 'tcp' ? DEFAULT_PORT_TCP : DEFAULT_PORT_RTU; }

    // --- Inicialización ---
    function bindEventListeners() { connectBtn.addEventListener('click', handleConnectClick); disconnectBtn.addEventListener('click', handleDisconnectClick); updateParamsBtn.addEventListener('click', handleUpdateParamsClick); readNowBtn.addEventListener('click', handleReadNowClick); toggleDebugBtn.addEventListener('click', handleToggleDebugClick); modeSelect.addEventListener('change', handleModeChange); handleModeChange(); }
    async function checkInitialState() { /* ... (igual, no inicia data polling) ... */ console.debug("Checking initial state..."); try { const status=await apiFetch('/api/status'); updateUIFromStatus(status); if(status.connected||status.is_connecting){ startStatusPolling(); startDebugPollingIfNeeded(); if(status.connected){ const regData=await apiFetch('/api/registers').catch(()=>({})); startAddrInput.value=regData.start_addr??0; regCountInput.value=regData.count??10; formatSelect.value=regData.format||'dec'; /* fetchDataAndUpdateUI(); // Opcional: leer al cargar si ya está conectado */ } } else { stopAllPolling(true); } } catch(error){ updateUIFromStatus({connected:false,is_connecting:false,message:"No se pudo obtener estado inicial.",last_error:error.message}); stopAllPolling(true); } }

    bindEventListeners(); checkInitialState();

}); // Fin DOMContentLoaded