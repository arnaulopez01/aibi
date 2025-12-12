// static/js/app.js

// Variables de Estado
let currentFileSummary = null;
let currentFilePath = null;
let currentDashId = null; 
let activeFilters = {};   
let mapInstances = {}; 
let pieColorMap = {}; // Memoria para persistencia de colores

document.addEventListener('DOMContentLoaded', () => {
    if(document.getElementById("historyList")) {
        loadHistory();
    }
});

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
            if(data.original_name) fileInput.dataset.originalName = data.original_name;

            label.textContent = "✅ " + file.name;
            label.classList.add("text-green-600");
            document.getElementById("promptContainer").classList.remove("opacity-50", "pointer-events-none");
        } catch (err) { alert(err.message); }
    });
}

// --- GENERACIÓN ---
async function generate() {
    const instruction = document.getElementById("prompt").value;
    const originalName = document.getElementById("fileInput").dataset.originalName;

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
                original_name: originalName
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
    mapInstances = {}; 
    pieColorMap = {}; // Resetear memoria de colores
    
    const inputSec = document.getElementById("inputSection");
    if(inputSec) inputSec.classList.add("hidden");

    document.getElementById("dashboardGrid").innerHTML = "";
    
    const loader = document.getElementById("loader");
    if(loader) {
        loader.classList.remove("hidden");
        loader.classList.add("flex");
    }

    try {
        const res = await fetch(`/api/dashboards/${id}`);
        const config = await res.json();
        if (config.error) throw new Error(config.error);
        renderDashboard(config);
    } catch(e) { alert("Error: " + e.message); } 
    finally {
        if(loader) {
            loader.classList.add("hidden");
            loader.classList.remove("flex");
        }
    }
}

// --- FULLSCREEN ---
function openFullscreen() {
    if (!currentDashId) return;
    const url = `/view/${currentDashId}`;
    window.open(url, '_blank');
}

function resetView() {
    currentDashId = null;
    activeFilters = {};
    mapInstances = {};
    pieColorMap = {};
    document.getElementById("inputSection").classList.remove("hidden");
    document.getElementById("dashboardGrid").classList.add("hidden");
    document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> Nuevo Análisis`;
    const btnFull = document.getElementById("btnFullscreen");
    if(btnFull) btnFull.classList.add("hidden");
}

// --- INTERACTIVIDAD ---
async function applyFilter(column, value) {
    if (!currentDashId) return;

    if (activeFilters[column] === value) delete activeFilters[column]; 
    else activeFilters[column] = value; 

    const grid = document.getElementById("dashboardGrid");
    grid.style.opacity = "0.7";

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
    }
}

function renderFilterTags() {
    let tagContainer = document.getElementById("filterTags");
    if (!tagContainer) {
        tagContainer = document.createElement("div");
        tagContainer.id = "filterTags";
        tagContainer.className = "flex gap-2 mb-4 flex-wrap px-6";
        const grid = document.getElementById("dashboardGrid");
        if(grid) grid.parentNode.insertBefore(tagContainer, grid);
    }
    
    tagContainer.innerHTML = "";
    Object.entries(activeFilters).forEach(([col, val]) => {
        const tag = document.createElement("span");
        tag.className = "bg-indigo-600 text-white text-xs font-bold px-3 py-1 rounded-full flex items-center gap-2 shadow-sm animate-pulse";
        tag.innerHTML = `${col}: ${val} <button onclick="applyFilter('${col}', '${val}')" class="hover:text-indigo-200">✕</button>`;
        tagContainer.appendChild(tag);
    });
}

// --- RENDERIZADO DEL DASHBOARD ---
function renderDashboard(config) {
    const mainContainer = document.getElementById("dashboardGrid");
    mainContainer.innerHTML = "";
    mainContainer.classList.remove("hidden");
    mainContainer.className = "pb-20"; 

    document.getElementById("pageTitle").innerHTML = `<span class="bg-indigo-100 text-indigo-700 p-1 rounded">📊</span> ${config.title || "Dashboard"}`;
    const oldTags = document.getElementById("filterTags");
    if(oldTags) oldTags.innerHTML = "";

    // 1. Separar componentes
    const maps = config.components.filter(c => c.type === 'map');
    const kpis = config.components.filter(c => c.type === 'kpi');
    const charts = config.components.filter(c => c.type === 'chart');

    // 2. RENDERIZAR PARTE SUPERIOR (Map + KPIs)
    if (maps.length > 0) {
        const topSection = document.createElement("div");
        // Layout: Mapa (3/4) | KPIs (1/4)
        topSection.className = "grid grid-cols-1 lg:grid-cols-4 gap-6 mb-6 h-auto lg:h-[500px]"; 
        
        // A. MAPA
        const mapComp = maps[0];
        const mapCard = document.createElement("div");
        mapCard.className = "lg:col-span-3 bg-white p-1 rounded-2xl shadow-sm border border-slate-200 h-[400px] lg:h-full relative overflow-hidden";
        
        const mapId = "map_" + mapComp.id;
        // Solo el contenedor, sin título
        mapCard.innerHTML = `<div id="${mapId}" class="w-full h-full rounded-xl bg-slate-100 relative"></div>`;
        topSection.appendChild(mapCard);
        
        // B. KPIS
        const kpiCol = document.createElement("div");
        kpiCol.className = "lg:col-span-1 flex flex-col gap-6 h-full";
        
        kpis.forEach(kpi => {
            const kpiCard = createKpiCard(kpi);
            kpiCard.classList.add("flex-grow");
            kpiCol.appendChild(kpiCard);
        });
        topSection.appendChild(kpiCol);
        
        mainContainer.appendChild(topSection);
        
        setTimeout(() => initMap(mapId, mapComp), 100);

    } else {
        // Fallback: Si no hay mapa, KPIs horizontales
        if (kpis.length > 0) {
            const kpiRow = document.createElement("div");
            kpiRow.className = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-6";
            kpis.forEach(kpi => {
                kpiRow.appendChild(createKpiCard(kpi));
            });
            mainContainer.appendChild(kpiRow);
        }
    }

    // 3. RENDERIZAR PARTE INFERIOR (Charts)
    if (charts.length > 0) {
        const chartGrid = document.createElement("div");
        chartGrid.className = "grid grid-cols-1 lg:grid-cols-2 gap-6";
        
        charts.forEach((comp, idx) => {
            const card = document.createElement("div");
            card.className = "bg-white p-6 rounded-2xl shadow-sm border border-slate-200 h-[400px] flex flex-col relative";
            const headerHtml = `<div class="mb-2"><h3 class="font-bold text-slate-800 text-lg leading-tight">${comp.title}</h3></div>`;
            const chartId = "chart_" + comp.id;
            card.innerHTML = headerHtml + `<div id="${chartId}" class="flex-grow w-full h-full"></div>`;
            
            if(activeFilters[comp.config.x]) card.classList.add("ring-2", "ring-indigo-500");
            
            chartGrid.appendChild(card);
            setTimeout(() => initChart(chartId, comp, idx), 50);
        });
        mainContainer.appendChild(chartGrid);
    }

    const btnFull = document.getElementById("btnFullscreen");
    if(btnFull) btnFull.classList.remove("hidden");
}

function createKpiCard(comp) {
    const card = document.createElement("div");
    card.className = "bg-white p-6 rounded-2xl shadow-sm border border-slate-200 flex flex-col justify-center items-center text-center hover:shadow-md transition";
    card.innerHTML = `
        <h3 class="font-bold text-slate-500 text-sm uppercase tracking-wider mb-2">${comp.title}</h3>
        <div id="kpi_val_${comp.id}" class="text-4xl lg:text-5xl font-extrabold text-slate-900 tracking-tight">
            ${formatNumber(comp.data.value)}
        </div>
        ${comp.description ? `<p class="text-xs text-slate-400 mt-2">${comp.description}</p>` : ''}
    `;
    return card;
}

// --- ACTUALIZACIÓN DE DATOS ---
function updateComponentsData(components) {
    components.forEach(comp => {
        if (comp.type === 'chart') {
            const chartInstance = echarts.getInstanceByDom(document.getElementById("chart_" + comp.id));
            if (chartInstance) {
                chartInstance.setOption({ dataset: { source: comp.data.source } });
            }
        } else if (comp.type === 'kpi') {
            const kpiValEl = document.getElementById("kpi_val_" + comp.id);
            if (kpiValEl) kpiValEl.innerText = formatNumber(comp.data.value);
        } else if (comp.type === 'map') {
             // Actualización suave del mapa
             const map = mapInstances[comp.id];
             if (map && map.getSource('points')) {
                 const newGeoJSON = createGeoJSON(comp.data, comp.config);
                 map.getSource('points').setData(newGeoJSON);
             } else {
                 const mapId = "map_" + comp.id;
                 const mapContainer = document.getElementById(mapId);
                 if (mapContainer) {
                     mapContainer.innerHTML = ""; 
                     initMap(mapId, comp); 
                 }
             }
        }
    });
}

// --- HELPERS ---

function createGeoJSON(data, config) {
    const latCol = config.lat;
    const lonCol = config.lon;
    
    const features = data.map(row => {
        const lat = parseFloat(row[latCol]);
        const lon = parseFloat(row[lonCol]);
        if (isNaN(lat) || isNaN(lon)) return null;

        let popupContent = `<div class="p-1">`;
        Object.entries(row).forEach(([k, v]) => {
            if(k !== latCol && k !== lonCol) popupContent += `<span class="text-xs text-slate-600"><b>${k}:</b> ${v}</span><br/>`;
        });
        popupContent += "</div>";

        return {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [lon, lat] },
            properties: { description: popupContent }
        };
    }).filter(f => f !== null);

    return { type: 'FeatureCollection', features: features };
}

function formatNumber(val) {
    if (typeof val === 'number') {
        return new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 }).format(val);
    }
    return val;
}

function initChart(domId, comp, idx) {
    const dom = document.getElementById(domId);
    if (!dom) return;
    const myChart = echarts.init(dom);
    const isPie = comp.chart_type === 'pie';
    
    // Paleta vibrante y ordenada
    const colors = [
        '#6366f1', '#10b981', '#f59e0b', '#ec4899', 
        '#3b82f6', '#8b5cf6', '#ef4444', '#06b6d4',
        '#84cc16', '#14b8a6', '#f97316', '#64748b'
    ];
    const themeColor = colors[idx % colors.length];

    // LÓGICA DE MEMORIA DE COLORES
    if (isPie) {
        if (!pieColorMap[comp.id]) pieColorMap[comp.id] = {};
        
        let nextColorIdx = Object.keys(pieColorMap[comp.id]).length;
        // Asumimos dim[0] es la categoría
        const catField = comp.data.dimensions[0]; 
        
        comp.data.source.forEach(row => {
            const name = row[catField];
            if (!pieColorMap[comp.id][name]) {
                // Asignar siguiente color de la paleta
                pieColorMap[comp.id][name] = colors[nextColorIdx % colors.length];
                nextColorIdx++;
            }
        });
    }

    const option = {
        color: isPie ? colors : [themeColor],
        tooltip: { 
            trigger: isPie ? 'item' : 'axis', 
            backgroundColor: 'rgba(255,255,255,0.95)', 
            padding: 12,
            textStyle: { color: '#1e293b' },
            valueFormatter: (value) => formatNumber(value)
        },
        grid: { left: '3%', right: '4%', bottom: '10%', top: '15%', containLabel: true },
        dataset: { dimensions: comp.data.dimensions, source: comp.data.source },
        xAxis: isPie ? { show: false } : { 
            type: 'category', 
            axisLabel: { rotate: 25, fontSize: 11, color: '#64748b', interval: 0 } 
        },
        yAxis: isPie ? { show: false } : { 
            type: 'value', 
            splitLine: { lineStyle: { type: 'dashed', color: '#f1f5f9' } } 
        },
        series: [{
            type: comp.chart_type || 'bar',
            radius: isPie ? ['40%', '70%'] : undefined,
            itemStyle: { 
                borderRadius: isPie ? 5 : [4, 4, 0, 0],
                borderColor: '#fff',
                borderWidth: isPie ? 2 : 0,
                // Si es Pie, consultamos la memoria, si no, color del tema
                color: isPie ? (params) => {
                    return pieColorMap[comp.id][params.name] || themeColor;
                } : themeColor
            },
            label: { show: isPie, formatter: '{b}: {d}%' }
        }]
    };
    myChart.setOption(option);
    window.addEventListener("resize", () => myChart.resize());

    myChart.on('click', function(params) {
        if (comp.config && comp.config.x && params.name !== 'Otros') {
            applyFilter(comp.config.x, params.name);
        }
    });
    myChart.getZr().setCursorStyle('pointer');
}

// --- INIT MAPA (Instantáneo) ---
function initMap(domId, comp) {
    const dom = document.getElementById(domId);
    if (!dom) return;

    const geoJSON = createGeoJSON(comp.data, comp.config);
    if (geoJSON.features.length === 0) {
        dom.innerHTML = "<div class='flex items-center justify-center h-full text-slate-400'>Sin coordenadas válidas</div>";
        return;
    }

    // Calcular bounds antes para zoom instantáneo
    const bounds = new maplibregl.LngLatBounds();
    geoJSON.features.forEach(feature => bounds.extend(feature.geometry.coordinates));

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
        bounds: bounds, // <--- CLAVE PARA NO ANIMAR
        fitBoundsOptions: { padding: 80, maxZoom: 14 }
    });

    mapInstances[comp.id] = map;

    map.on('load', () => {
        map.addSource('points', { type: 'geojson', data: geoJSON });

        map.addLayer({
            id: 'points-layer',
            type: 'circle',
            source: 'points',
            paint: {
                'circle-radius': 6,
                'circle-color': '#4f46e5',
                'circle-stroke-width': 2,
                'circle-stroke-color': '#ffffff',
                'circle-opacity': 0.8
            }
        });

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

        map.on('mouseenter', 'points-layer', () => map.getCanvas().style.cursor = 'pointer');
        map.on('mouseleave', 'points-layer', () => map.getCanvas().style.cursor = '');
    });
}