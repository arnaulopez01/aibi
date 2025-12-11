// static/js/app.js

// Variables de Estado
let currentFileSummary = null;
let currentFilePath = null;
let currentDataTypes = null;

// Inicialización: Cargar historial al abrir
document.addEventListener('DOMContentLoaded', loadHistory);

// --- GESTIÓN DE SESIÓN ---
async function logout() {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/";
}

// --- SUBIDA DE ARCHIVOS ---
const fileInput = document.getElementById("fileInput");
if(fileInput) {
    fileInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const label = document.getElementById("fileName");
        label.textContent = "Subiendo...";
        
        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch("/upload_and_analyze", { method: "POST", body: formData });
            const data = await res.json();

            if (data.error) throw new Error(data.error);

            currentFileSummary = data.summary;
            currentFilePath = data.file_path;
            currentDataTypes = data.col_types;

            label.textContent = "✅ " + file.name;
            label.classList.add("text-green-600");
            document.getElementById("promptContainer").classList.remove("opacity-50", "pointer-events-none");

        } catch (err) {
            alert(err.message);
            label.textContent = "Error al subir";
            label.classList.add("text-red-500");
        }
    });
}

// --- GENERACIÓN ---
async function generate() {
    const instruction = document.getElementById("prompt").value;
    
    document.getElementById("inputSection").classList.add("hidden");
    document.getElementById("loader").classList.remove("hidden");
    document.getElementById("loader").classList.add("flex");

    try {
        const res = await fetch("/generate_dashboard", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                file_path: currentFilePath,
                summary: currentFileSummary,
                instruction: instruction,
                col_types: currentDataTypes
            })
        });

        const data = await res.json();
        if (data.error) throw new Error(data.error);

        renderDashboard(data.config, data.data, data.col_types);
        loadHistory(); 

    } catch (e) {
        alert("Error: " + e.message);
        document.getElementById("inputSection").classList.remove("hidden");
    } finally {
        document.getElementById("loader").classList.add("hidden");
        document.getElementById("loader").classList.remove("flex");
    }
}

// --- HISTORIAL ---

async function loadHistory() {
    const list = document.getElementById("historyList");
    if (!list) return;

    try {
        const res = await fetch("/api/dashboards");
        const items = await res.json();
        
        list.innerHTML = "";
        
        if (items.length === 0) {
            list.innerHTML = '<p class="text-xs text-slate-500 text-center mt-4">Sin historial reciente</p>';
            return;
        }

        items.forEach(item => {
            const div = document.createElement("div");
            // Usamos 'group' para controlar la visibilidad del botón de borrar al hacer hover
            div.className = "group flex items-center justify-between p-3 mb-1 rounded-xl cursor-pointer hover:bg-slate-800 transition border border-transparent hover:border-slate-700/50";
            
            // HTML del item + Botón de borrar (oculto por defecto con opacity-0)
            div.innerHTML = `
                <div class="flex-grow min-w-0 pr-2" onclick="loadDashboard('${item.id}')">
                    <div class="font-medium text-slate-300 group-hover:text-white truncate text-sm transition">${item.title}</div>
                    <div class="text-[10px] text-slate-500 group-hover:text-slate-400">${new Date(item.created_at).toLocaleDateString()}</div>
                </div>
                <button onclick="deleteDashboard('${item.id}', event)" class="opacity-0 group-hover:opacity-100 p-1.5 text-slate-500 hover:text-red-400 hover:bg-slate-700 rounded-lg transition-all transform hover:scale-110" title="Borrar">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                </button>
            `;
            list.appendChild(div);
        });
    } catch(e) { console.error(e); }
}

// 2. Añade esta nueva función para manejar el borrado
async function deleteDashboard(id, event) {
    // Importante: Evita que el click se propague al div padre y abra el dashboard
    event.stopPropagation(); 

    if (!confirm("¿Estás seguro de que quieres eliminar este análisis? Esta acción no se puede deshacer.")) {
        return;
    }

    try {
        const res = await fetch(`/api/dashboards/${id}`, {
            method: "DELETE"
        });

        if (res.ok) {
            // Si estás viendo el dashboard que acabas de borrar, resetea la vista
            const currentTitle = document.getElementById("pageTitle").textContent;
            // Una comprobación simple (podríamos mejorarla guardando el ID actual en variable global)
            
            // Recargar la lista del historial
            loadHistory();
            
            // Opcional: Si el dashboard borrado es el que está en pantalla, limpiar
            // resetView(); 
        } else {
            alert("Error al eliminar el dashboard");
        }
    } catch (e) {
        console.error(e);
        alert("Error de conexión");
    }
}
async function loadDashboard(id) {
    document.getElementById("inputSection").classList.add("hidden");
    document.getElementById("dashboardGrid").innerHTML = "";
    document.getElementById("loader").classList.remove("hidden");
    document.getElementById("loader").classList.add("flex");

    try {
        const res = await fetch(`/api/dashboards/${id}`);
        const data = await res.json();
        
        if (data.error) throw new Error(data.error);
        
        document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> ${data.config.dashboard_title}`;
        renderDashboard(data.config, data.data, data.col_types);

    } catch(e) {
        alert("Error: " + e.message);
    } finally {
        document.getElementById("loader").classList.add("hidden");
        document.getElementById("loader").classList.remove("flex");
    }
}

function resetView() {
    document.getElementById("inputSection").classList.remove("hidden");
    document.getElementById("dashboardGrid").classList.add("hidden");
    document.getElementById("prompt").value = "";
    document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> Nuevo Análisis`;
    document.getElementById("fileName").textContent = "Sube tu CSV o Excel";
    document.getElementById("fileName").classList.remove("text-green-600");
    document.getElementById("promptContainer").classList.add("opacity-50", "pointer-events-none");
}

// --- RENDERIZADO (ECHARTS) ---
function renderDashboard(config, dataRecords, colTypes) {
    const grid = document.getElementById("dashboardGrid");
    grid.innerHTML = "";
    grid.classList.remove("hidden");

    if (!config.charts || config.charts.length === 0) {
        grid.innerHTML = "<p>No charts</p>"; return;
    }

    config.charts.forEach((chartConf, idx) => {
        const card = document.createElement("div");
        card.className = "bg-white p-6 rounded-2xl shadow-sm border border-slate-200 flex flex-col h-[400px] hover:shadow-md transition";
        if (idx === 0 && config.charts.length === 3) card.classList.add("md:col-span-2");

        const chartId = "chart_" + Math.random().toString(36).substr(2, 9);
        card.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <h3 class="font-bold text-slate-800 text-lg">${chartConf.title}</h3>
                <span class="text-[10px] uppercase font-bold bg-slate-100 text-slate-500 px-2 py-1 rounded">${chartConf.type}</span>
            </div>
            <p class="text-xs text-slate-500 mb-4 truncate">${chartConf.description || ""}</p>
            <div id="${chartId}" class="flex-grow w-full"></div>
        `;
        grid.appendChild(card);

        setTimeout(() => {
            const chartDom = document.getElementById(chartId);
            if (!chartDom) return;
            const myChart = echarts.init(chartDom);
            const processedData = processData(dataRecords, chartConf.x_column, chartConf.y_column);
            
            if (processedData.length === 0) {
                chartDom.innerHTML = "<div class='flex h-full items-center justify-center text-slate-400'>Sin datos</div>";
                return;
            }

            myChart.setOption(buildOption(chartConf, processedData));
            window.addEventListener("resize", () => myChart.resize());
        }, 50);
    });
}

function processData(df, xCol, yCol) {
    if (!df || df.length === 0) return [];
    const findKey = (row, key) => Object.keys(row).find(k => k.toLowerCase() === (key||"").toLowerCase());
    const out = {};
    
    df.forEach(row => {
        let actualX = findKey(row, xCol) || xCol;
        let actualY = findKey(row, yCol) || yCol;
        let key = (row[actualX] == null) ? "N/A" : String(row[actualX]);
        
        let val = 0;
        if (yCol === "__conteo__" || !yCol) val = 1;
        else {
            let rawVal = row[actualY];
            if (rawVal != null) {
                if (typeof rawVal === 'string') val = parseFloat(rawVal.replace(/[^\d.-]/g, ""));
                else val = Number(rawVal);
            }
        }
        if (isNaN(val)) val = 0;
        out[key] = (out[key] || 0) + val;
    });

    return Object.entries(out).map(([k, v]) => ({ name: k, value: v })).sort((a, b) => b.value - a.value).slice(0, 30);
}

function buildOption(conf, data) {
    const isPie = conf.type === 'pie';
    const colors = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#10b981', '#3b82f6'];
    const tooltip = { trigger: isPie ? 'item' : 'axis', backgroundColor: 'rgba(255,255,255,0.95)' };

    if (isPie) {
        return {
            color: colors, tooltip, legend: { bottom: 0, type: 'scroll' },
            series: [{ type: 'pie', radius: ['40%', '70%'], itemStyle: { borderRadius: 5, borderColor: '#fff', borderWidth: 2 }, data }]
        };
    }
    return {
        color: colors, tooltip, grid: { left: '3%', right: '4%', bottom: '10%', containLabel: true },
        xAxis: { type: 'category', data: data.map(d => d.name), axisLabel: { rotate: 30, fontSize: 11 } },
        yAxis: { type: 'value' },
        series: [{ type: conf.type || 'bar', data: data.map(d => d.value), itemStyle: { borderRadius: [4, 4, 0, 0] } }]
    };
}