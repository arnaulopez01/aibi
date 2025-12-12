// static/js/app.js

// Variables de Estado
let currentFileSummary = null;
let currentFilePath = null;
let currentDashId = null; 
let activeFilters = {};   

document.addEventListener('DOMContentLoaded', loadHistory);

// --- GESTIÓN DE SESIÓN ---
async function logout() {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/";
}

// --- SUBIDA ---
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
            label.textContent = "✅ " + file.name;
            label.classList.add("text-green-600");
            document.getElementById("promptContainer").classList.remove("opacity-50", "pointer-events-none");
        } catch (err) { alert(err.message); }
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
                instruction: instruction
            })
        });
        const config = await res.json();
        if (config.error) throw new Error(config.error);

        await loadHistory();
        const firstItem = document.querySelector("#historyList > div > div");
        if(firstItem) firstItem.click(); 

    } catch (e) {
        alert("Error: " + e.message);
        document.getElementById("inputSection").classList.remove("hidden");
        document.getElementById("loader").classList.add("hidden");
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
            list.innerHTML = '<p class="text-xs text-slate-500 text-center mt-4">Sin historial</p>';
            return;
        }
        items.forEach(item => {
            const div = document.createElement("div");
            div.className = "group flex items-center justify-between p-3 mb-1 rounded-xl cursor-pointer hover:bg-slate-800 transition border border-transparent hover:border-slate-700/50";
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

async function deleteDashboard(id, event) {
    event.stopPropagation();
    if (!confirm("¿Eliminar?")) return;
    await fetch(`/api/dashboards/${id}`, { method: "DELETE" });
    loadHistory();
    if(currentDashId === id) resetView();
}

async function loadDashboard(id) {
    currentDashId = id;
    activeFilters = {}; 
    document.getElementById("inputSection").classList.add("hidden");
    document.getElementById("dashboardGrid").innerHTML = "";
    document.getElementById("loader").classList.remove("hidden");
    document.getElementById("loader").classList.add("flex");

    try {
        const res = await fetch(`/api/dashboards/${id}`);
        const config = await res.json();
        if (config.error) throw new Error(config.error);
        renderDashboard(config);
    } catch(e) { alert("Error: " + e.message); } 
    finally {
        document.getElementById("loader").classList.add("hidden");
        document.getElementById("loader").classList.remove("flex");
    }
}

function resetView() {
    currentDashId = null;
    activeFilters = {};
    document.getElementById("inputSection").classList.remove("hidden");
    document.getElementById("dashboardGrid").classList.add("hidden");
    document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> Nuevo Análisis`;
}

// --- INTERACTIVIDAD ---
async function applyFilter(column, value) {
    if (!currentDashId) return;

    if (activeFilters[column] === value) delete activeFilters[column]; 
    else activeFilters[column] = value; 

    const grid = document.getElementById("dashboardGrid");
    grid.style.opacity = "0.6";
    grid.style.pointerEvents = "none";

    try {
        const res = await fetch(`/api/dashboards/${currentDashId}/filter`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filters: activeFilters })
        });
        
        const data = await res.json();
        updateComponentsData(data.components);
        renderFilterTags();

    } catch(e) {
        console.error(e);
        alert("Error al filtrar");
    } finally {
        grid.style.opacity = "1";
        grid.style.pointerEvents = "auto";
    }
}

function renderFilterTags() {
    let tagContainer = document.getElementById("filterTags");
    if (!tagContainer) {
        tagContainer = document.createElement("div");
        tagContainer.id = "filterTags";
        tagContainer.className = "flex gap-2 mb-4 flex-wrap px-6";
        document.getElementById("mainScroll").insertBefore(tagContainer, document.getElementById("dashboardGrid"));
    }
    
    tagContainer.innerHTML = "";
    Object.entries(activeFilters).forEach(([col, val]) => {
        const tag = document.createElement("span");
        tag.className = "bg-indigo-600 text-white text-xs font-bold px-3 py-1 rounded-full flex items-center gap-2 shadow-sm animate-pulse";
        tag.innerHTML = `${col}: ${val} <button onclick="applyFilter('${col}', '${val}')" class="hover:text-indigo-200">✕</button>`;
        tagContainer.appendChild(tag);
    });
}

// --- RENDERIZADO ---
function renderDashboard(config) {
    const grid = document.getElementById("dashboardGrid");
    grid.innerHTML = "";
    grid.classList.remove("hidden");
    document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> ${config.title || "Dashboard"}`;

    const oldTags = document.getElementById("filterTags");
    if(oldTags) oldTags.innerHTML = "";

    config.components.forEach((comp, idx) => {
        if (!comp.data) return;

        const card = document.createElement("div");
        card.className = "bg-white p-6 rounded-2xl shadow-sm border border-slate-200 flex flex-col hover:shadow-md transition duration-300 relative group";
        
        const headerHtml = `
            <div class="mb-4">
                <h3 class="font-bold text-slate-800 text-lg leading-tight">${comp.title}</h3>
                <p class="text-xs text-slate-500 truncate">${comp.description || ''}</p>
            </div>
        `;

        if (comp.type === 'kpi') {
            card.classList.add("col-span-1", "h-40");
            card.innerHTML = headerHtml + renderKPI(comp.data, comp.id);
        } else {
            card.classList.add("col-span-1", "h-[400px]");
            if (comp.chart_type === 'map' || config.components.length === 1) card.classList.add("lg:col-span-2");
            
            if (comp.type === 'chart') {
                const chartId = "chart_" + comp.id;
                card.innerHTML = headerHtml + `<div id="${chartId}" class="flex-grow w-full h-full"></div>`;
                if(activeFilters[comp.config.x]) card.classList.add("ring-2", "ring-indigo-500");
                grid.appendChild(card);
                setTimeout(() => initChart(chartId, comp, idx), 50);
                return;
            } else if (comp.type === 'map') {
                const mapId = "map_" + comp.id;
                // Importante: MapLibre necesita un contenedor relativo con dimensiones definidas
                card.innerHTML = headerHtml + `<div id="${mapId}" class="flex-grow w-full h-full rounded-xl overflow-hidden bg-slate-100 relative"></div>`;
                grid.appendChild(card);
                setTimeout(() => initMap(mapId, comp), 100); // Un poco más de delay para asegurar render
                return;
            }
        }
        grid.appendChild(card);
    });
}

function updateComponentsData(components) {
    components.forEach(comp => {
        if (comp.type === 'chart') {
            const chartInstance = echarts.getInstanceByDom(document.getElementById("chart_" + comp.id));
            if (chartInstance) {
                chartInstance.setOption({
                    dataset: { source: comp.data.source }
                });
            }
        } else if (comp.type === 'kpi') {
            const kpiValEl = document.getElementById("kpi_val_" + comp.id);
            if (kpiValEl) kpiValEl.innerText = formatNumber(comp.data.value);
        } else if (comp.type === 'map') {
            // Mapas son complejos de actualizar parcialmente sin recargar el dashboard
            // o sin lógica compleja de capas. 
            // Para simplificar y asegurar que funciona, recargamos el mapa entero.
             const mapId = "map_" + comp.id;
             const mapContainer = document.getElementById(mapId);
             if (mapContainer) {
                 mapContainer.innerHTML = ""; // Limpiar
                 initMap(mapId, comp); // Repintar
             }
        }
    });
}

function formatNumber(val) {
    if (typeof val === 'number') {
        return new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2, notation: "compact" }).format(val);
    }
    return val;
}

// --- CAMBIO: TEXTO KPI NEGRO ---
function renderKPI(data, id) {
    return `
        <div class="flex flex-grow items-center justify-center">
            <span id="kpi_val_${id}" class="text-5xl font-extrabold text-slate-900 tracking-tight">
                ${formatNumber(data.value)}
            </span>
        </div>
    `;
}

function initChart(domId, comp, idx) {
    const dom = document.getElementById(domId);
    if (!dom) return;
    const myChart = echarts.init(dom);
    const isPie = comp.chart_type === 'pie';
    const isLine = comp.chart_type === 'line';
    
    // Paleta de colores vibrantes
    const colors = [
        '#6366f1', '#10b981', '#f59e0b', '#ec4899', 
        '#3b82f6', '#8b5cf6', '#ef4444', '#06b6d4'
    ];
    // Color único por gráfico
    const themeColor = colors[idx % colors.length];

    const option = {
        color: isPie ? colors : [themeColor],
        tooltip: { trigger: isPie ? 'item' : 'axis', backgroundColor: 'rgba(255,255,255,0.95)', padding: 12 },
        grid: { left: '3%', right: '4%', bottom: '10%', top: '15%', containLabel: true },
        dataset: { dimensions: comp.data.dimensions, source: comp.data.source },
        xAxis: isPie ? { show: false } : { type: 'category', axisLabel: { rotate: 25, fontSize: 11, color: '#64748b' } },
        yAxis: isPie ? { show: false } : { type: 'value', splitLine: { lineStyle: { type: 'dashed', color: '#f1f5f9' } } },
        series: [{
            type: comp.chart_type || 'bar',
            radius: isPie ? ['40%', '70%'] : undefined,
            itemStyle: { 
                borderRadius: isPie ? 5 : [4, 4, 0, 0],
                color: isPie ? undefined : themeColor
            },
            colorBy: (isLine) ? 'series' : 'series' // Forzamos series para mantener color uniforme en barras
        }]
    };
    myChart.setOption(option);
    window.addEventListener("resize", () => myChart.resize());

    myChart.on('click', function(params) {
        if (comp.config && comp.config.x) {
            applyFilter(comp.config.x, params.name);
        }
    });
    myChart.getZr().setCursorStyle('pointer');
}

// --- CAMBIO: MAPLIBRE GL JS (OPENSTREETMAP) ---
function initMap(domId, comp) {
    const dom = document.getElementById(domId);
    if (!dom) return;

    // 1. Extraer nombres de columnas de lat/lon del config
    const latCol = comp.config.lat;
    const lonCol = comp.config.lon;

    // 2. Convertir datos a GeoJSON
    const features = comp.data.map(row => {
        // Aseguramos que son números
        const lat = parseFloat(row[latCol]);
        const lon = parseFloat(row[lonCol]);
        
        if (isNaN(lat) || isNaN(lon)) return null;

        // Crear tooltip html
        let popupContent = `<strong>${comp.title}</strong><br/>`;
        Object.entries(row).forEach(([k, v]) => {
            if(k !== latCol && k !== lonCol) popupContent += `${k}: ${v}<br/>`;
        });

        return {
            type: 'Feature',
            geometry: {
                type: 'Point',
                coordinates: [lon, lat] // GeoJSON es [lon, lat]
            },
            properties: {
                description: popupContent
            }
        };
    }).filter(f => f !== null);

    if (features.length === 0) {
        dom.innerHTML = "<div class='flex items-center justify-center h-full text-slate-400'>Sin coordenadas válidas</div>";
        return;
    }

    // 3. Inicializar Mapa
    const map = new maplibregl.Map({
        container: domId,
        style: {
            version: 8,
            sources: {
                'osm': {
                    type: 'raster',
                    tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
                    tileSize: 256,
                    attribution: '&copy; OpenStreetMap Contributors'
                }
            },
            layers: [{
                id: 'osm',
                type: 'raster',
                source: 'osm',
                minzoom: 0,
                maxzoom: 19
            }]
        },
        center: [0, 0],
        zoom: 1
    });

    map.on('load', () => {
        // Añadir fuente de datos
        map.addSource('points', {
            type: 'geojson',
            data: {
                type: 'FeatureCollection',
                features: features
            }
        });

        // Añadir capa de puntos (Círculos rojos)
        map.addLayer({
            id: 'points-layer',
            type: 'circle',
            source: 'points',
            paint: {
                'circle-radius': 6,
                'circle-color': '#ef4444', // Rojo vibrante
                'circle-stroke-width': 2,
                'circle-stroke-color': '#ffffff'
            }
        });

        // Configurar popups al clic
        map.on('click', 'points-layer', (e) => {
            const coordinates = e.features[0].geometry.coordinates.slice();
            const description = e.features[0].properties.description;

            while (Math.abs(e.lngLat.lng - coordinates[0]) > 180) {
                coordinates[0] += e.lngLat.lng > coordinates[0] ? 360 : -360;
            }

            new maplibregl.Popup()
                .setLngLat(coordinates)
                .setHTML(description)
                .addTo(map);
        });

        // Cambiar cursor
        map.on('mouseenter', 'points-layer', () => map.getCanvas().style.cursor = 'pointer');
        map.on('mouseleave', 'points-layer', () => map.getCanvas().style.cursor = '');

        // Auto-zoom para ver todos los puntos (Bbox)
        const bounds = new maplibregl.LngLatBounds();
        features.forEach(feature => bounds.extend(feature.geometry.coordinates));
        map.fitBounds(bounds, { padding: 50, maxZoom: 15 });
    });
}