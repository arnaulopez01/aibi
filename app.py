import os
import json
import uuid
import time
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from google import genai
from google.genai import types

# Cargar variables de entorno
load_dotenv()

# --- CONFIGURACIÓN BÁSICA ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_secret_key_super_segura")
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth_page'

# Configuración de Directorios
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DASHBOARD_DIR = os.path.join(DATA_DIR, 'dashboards')

for d in [DATA_DIR, UPLOAD_FOLDER, DASHBOARD_DIR]:
    os.makedirs(d, exist_ok=True)

if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f: json.dump({}, f)

# --- CONFIGURACIÓN GEMINI AI ---
# Usamos el modelo rápido que confirmamos
MODEL_NAME = "gemini-2.5-flash" 
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# --- PROMPT DEL ARQUITECTO DE DATOS ---
SYSTEM_PROMPT = """
Eres un Arquitecto de Datos experto en Business Intelligence.
Tu tarea es analizar la estructura de un dataset y la solicitud del usuario para diseñar un dashboard interactivo.
Genera ÚNICAMENTE un JSON válido con la configuración.

TU MISIÓN:
1. Selecciona los mejores gráficos o KPIs para responder al usuario.
2. Define la operación matemática (sum, mean, count) para cada componente.
3. Si detectas coordenadas (lat/lon), crea un componente tipo "map".

ESTRUCTURA DE RESPUESTA JSON:
{
  "title": "Título descriptivo del Dashboard",
  "components": [
    {
      "id": "c1",
      "type": "kpi", 
      "title": "Ingresos Totales",
      "description": "Suma total de la columna ventas",
      "config": {
        "operation": "sum",
        "column": "ventas",
        "format": "currency"
      }
    },
    {
      "id": "c2",
      "type": "chart",
      "chart_type": "bar", 
      "title": "Ventas por Categoría",
      "config": {
        "x": "categoria",
        "y": "ventas",
        "operation": "sum",
        "limit": 15
      }
    }
  ]
}

TIPOS PERMITIDOS ("type"): "kpi", "chart", "map".
TIPOS DE GRÁFICO ("chart_type"): "bar", "line", "pie", "scatter".
OPERACIONES ("operation"): "count" (cuenta filas), "sum", "mean", "max", "min".
"""

# --- MOTOR DE PROCESAMIENTO DE DATOS ---

def clean_dataframe(df):
    """Limpia valores infinitos y nulos básicos"""
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.where(pd.notnull(df), None)

def apply_global_filters(df, filters):
    """
    Filtra el DataFrame basado en los clics del usuario.
    filters = {'Ciudad': 'Madrid', 'Género': 'F'}
    """
    if not filters: return df
    
    df_filtered = df.copy()
    for col, val in filters.items():
        if col in df_filtered.columns:
            # Convertimos a string para asegurar comparación exacta
            df_filtered = df_filtered[df_filtered[col].astype(str) == str(val)]
            
    return df_filtered

def process_component_data(df, component):
    """
    Ejecuta las instrucciones matemáticas del JSON sobre el DataFrame.
    Devuelve los datos listos para pintar.
    """
    try:
        c_type = component.get('type')
        config = component.get('config', {})
        
        # --- 1. PROCESAR KPI (Un número) ---
        if c_type == 'kpi':
            op = config.get('operation', 'count')
            col = config.get('column')
            
            val = 0
            if op == 'count':
                val = len(df)
            elif col and col in df.columns:
                # Convertir a numérico forzoso
                numeric_series = pd.to_numeric(df[col], errors='coerce').fillna(0)
                if op == 'sum': val = numeric_series.sum()
                elif op == 'mean': val = numeric_series.mean()
                elif op == 'max': val = numeric_series.max()
                elif op == 'min': val = numeric_series.min()
            
            return {"value": val, "label": component.get('title')}

        # --- 2. PROCESAR MAPA ---
        elif c_type == 'map':
            lat = config.get('lat')
            lon = config.get('lon')
            label = config.get('label')
            
            if lat in df.columns and lon in df.columns:
                cols = [lat, lon]
                if label and label in df.columns: cols.append(label)
                # Muestra limitada para no saturar el mapa
                return df[cols].dropna().head(1000).to_dict(orient='records')
            return []

        # --- 3. PROCESAR GRÁFICO ---
        elif c_type == 'chart':
            x = config.get('x')
            y = config.get('y')
            op = config.get('operation', 'count')
            limit = config.get('limit', 20)
            
            if not x or x not in df.columns: return []

            # A. Agrupación y Cálculo
            if op == 'count':
                # Conteo de frecuencia
                df_res = df[x].value_counts().reset_index()
                df_res.columns = [x, 'value']
            
            elif y and y in df.columns:
                # Operación sobre columna Y
                df[y] = pd.to_numeric(df[y], errors='coerce').fillna(0)
                
                if op == 'sum': df_res = df.groupby(x)[y].sum().reset_index()
                elif op == 'mean': df_res = df.groupby(x)[y].mean().reset_index()
                else: df_res = df.groupby(x)[y].sum().reset_index()
                
                df_res.columns = [x, 'value']
            else:
                return []

            # B. Ordenar y Limitar (Top N)
            df_res = df_res.sort_values(by='value', ascending=False).head(limit)
            
            return {
                "dimensions": [x, 'value'],
                "source": df_res.to_dict(orient='records')
            }
            
        return None
    except Exception as e:
        print(f"Error procesando componente {component.get('id')}: {e}")
        return None

# --- GESTIÓN DE USUARIOS ---
class User(UserMixin):
    def __init__(self, id, email, password_hash):
        self.id = id
        self.email = email
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    try:
        with open(USERS_FILE, 'r') as f: users = json.load(f)
        if user_id in users:
            u = users[user_id]
            return User(user_id, u['email'], u['password'])
    except: pass
    return None

def save_new_user(email, password):
    with open(USERS_FILE, 'r') as f: users = json.load(f)
    
    # Check si existe
    for uid, data in users.items():
        if data['email'] == email:
            return User(uid, data['email'], data['password'])
    
    # Crear nuevo
    uid = str(uuid.uuid4())
    pw = bcrypt.generate_password_hash(password).decode('utf-8')
    users[uid] = {'email': email, 'password': pw}
    with open(USERS_FILE, 'w') as f: json.dump(users, f)
    return User(uid, email, pw)

def get_user_by_email(email):
    with open(USERS_FILE, 'r') as f: users = json.load(f)
    for uid, data in users.items():
        if data['email'] == email: return User(uid, data['email'], data['password'])
    return None

# --- RUTAS PÁGINAS ---
@app.route("/")
def index():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return render_template("home.html")

@app.route("/auth")
def auth_page():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return render_template("auth.html")

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)

# --- RUTAS AUTH (API) ---
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json
    user = get_user_by_email(data.get('email'))
    if user and bcrypt.check_password_hash(user.password_hash, data.get('password')):
        login_user(user)
        return jsonify({"message": "OK", "redirect": url_for('dashboard')})
    return jsonify({"error": "Credenciales incorrectas"}), 401

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.json
    if get_user_by_email(data.get('email')):
        return jsonify({"error": "Usuario ya existe"}), 400
    user = save_new_user(data.get('email'), data.get('password'))
    login_user(user)
    return jsonify({"message": "OK", "redirect": url_for('dashboard')})

@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"redirect": url_for('index')})

# --- RUTAS DE NEGOCIO (Upload & AI) ---

@app.route("/upload_and_analyze", methods=["POST"])
@login_required
def upload_and_analyze():
    if 'file' not in request.files: return jsonify({"error": "Falta archivo"}), 400
    file = request.files['file']
    
    user_path = os.path.join(UPLOAD_FOLDER, current_user.id)
    os.makedirs(user_path, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    filepath = os.path.join(user_path, filename)
    file.save(filepath)

    try:
        if filename.endswith('.csv'): df = pd.read_csv(filepath, engine='python')
        else: df = pd.read_excel(filepath)
        df.columns = df.columns.str.strip() # Limpiar nombres columnas
        
        # Resumen Optimizado para Tokens
        summary = [f"Filas Totales: {len(df)}"]
        for col in df.columns:
            dtype = str(df[col].dtype)
            # Muestra truncada para ahorrar tokens
            sample = [str(x)[:40] for x in df[col].dropna().head(3).tolist()]
            summary.append(f"- '{col}' ({dtype}): {sample}")
            
        return jsonify({
            "summary": "\n".join(summary),
            "file_path": os.path.join(current_user.id, filename)
        })
    except Exception as e:
        return jsonify({"error": f"Error leyendo archivo: {str(e)}"}), 500

@app.route("/generate_dashboard", methods=["POST"])
@login_required
def generate_dashboard():
    # Seguridad: Check API Key
    if not client:
        return jsonify({"error": "Error Servidor: Falta GEMINI_API_KEY en .env"}), 500

    data = request.json
    full_path = os.path.join(UPLOAD_FOLDER, data.get('file_path'))
    
    if not os.path.exists(full_path): return jsonify({"error": "Archivo perdido"}), 404

    try:
        # 1. Cargar Datos
        if full_path.endswith('.csv'): df = pd.read_csv(full_path, engine='python')
        else: df = pd.read_excel(full_path)
        df.columns = df.columns.str.strip()

        # 2. Generar Configuración con Gemini (con reintentos para 503)
        prompt = f"DATASET:\n{data.get('summary')}\nUSUARIO QUIERE:\n{data.get('instruction')}"
        
        response = None
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=[{"role": "user", "parts": [{"text": prompt}]}],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.3
                    )
                )
                break 
            except Exception as e:
                if attempt == max_retries - 1: raise e
                time.sleep(1.5 ** attempt) # Backoff exponencial

        config_json = json.loads(response.text)

        # 3. Procesar Componentes
        processed_components = []
        for comp in config_json.get('components', []):
            comp_data = process_component_data(df, comp)
            if comp_data:
                comp['data'] = comp_data
                processed_components.append(comp)

        final_config = {
            "title": config_json.get('title', 'Análisis Generado'),
            "components": processed_components
        }

        # 4. Guardar Dashboard
        dash_id = str(uuid.uuid4())
        user_dash_dir = os.path.join(DASHBOARD_DIR, current_user.id)
        os.makedirs(user_dash_dir, exist_ok=True)
        
        with open(os.path.join(user_dash_dir, f"{dash_id}.json"), 'w') as f:
            json.dump({
                "id": dash_id,
                "created_at": datetime.now().isoformat(),
                "config": final_config, # Guardamos la config base
                "file_path": data.get('file_path')
            }, f)

        return jsonify(final_config)

    except Exception as e:
        print(f"Error GenAI: {e}")
        return jsonify({"error": str(e)}), 500

# --- RUTAS GESTIÓN DASHBOARDS ---

@app.route("/api/dashboards", methods=["GET"])
@login_required
def list_dashboards():
    user_dir = os.path.join(DASHBOARD_DIR, current_user.id)
    if not os.path.exists(user_dir): return jsonify([])
    
    items = []
    for f in os.listdir(user_dir):
        if f.endswith('.json'):
            try:
                with open(os.path.join(user_dir, f)) as file:
                    d = json.load(file)
                    items.append({
                        "id": d['id'], 
                        "title": d.get('config', {}).get('title', 'Sin Título'), 
                        "created_at": d.get('created_at')
                    })
            except: pass
    items.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(items)

@app.route("/api/dashboards/<dash_id>", methods=["GET"])
@login_required
def get_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return jsonify({"error": "No existe"}), 404
    
    with open(path) as f: dash_data = json.load(f)
    return jsonify(dash_data['config'])

@app.route("/api/dashboards/<dash_id>", methods=["DELETE"])
@login_required
def delete_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return jsonify({"message": "Borrado"})
    return jsonify({"error": "No encontrado"}), 404

# --- NUEVA RUTA: FILTRADO INTERACTIVO ---

@app.route("/api/dashboards/<dash_id>/filter", methods=["POST"])
@login_required
def filter_dashboard(dash_id):
    # 1. Obtener Filtros
    filters = request.json.get('filters', {})
    
    # 2. Cargar Config Original
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return jsonify({"error": "Error carga"}), 404
    
    with open(path) as f: dash_data = json.load(f)
    
    # 3. Cargar DataFrame Original
    full_path = os.path.join(UPLOAD_FOLDER, dash_data['file_path'])
    if full_path.endswith('.csv'): df = pd.read_csv(full_path, engine='python')
    else: df = pd.read_excel(full_path)
    df.columns = df.columns.str.strip()
    
    # 4. Aplicar Filtros Globales
    df_filtered = apply_global_filters(df, filters)
    
    # 5. Recalcular Todos los Componentes
    updated_components = []
    for comp in dash_data['config']['components']:
        # Usamos la definición original del componente, pero con df filtrado
        new_data = process_component_data(df_filtered, comp)
        if new_data:
            comp['data'] = new_data
            updated_components.append(comp)
            
    return jsonify({
        "components": updated_components,
        "active_filters": filters
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)