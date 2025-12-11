import os
import json
import uuid
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from google import genai
from google.genai import types

load_dotenv()

# --- CONFIGURACIÓN ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_secret_key_change_in_prod")
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth_page'

# Directorios
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DASHBOARD_DIR = os.path.join(DATA_DIR, 'dashboards')

for d in [DATA_DIR, UPLOAD_FOLDER, DASHBOARD_DIR]:
    os.makedirs(d, exist_ok=True)

if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f: json.dump({}, f)

# Cliente Gemini
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None
MODEL_NAME = "gemini-2.5-flash"

# --- EL CEREBRO (Prompt de Ingeniería) ---
SYSTEM_PROMPT = """
Eres un Arquitecto de Datos experto en BI. Tu objetivo es analizar la estructura de un dataset y la petición del usuario para diseñar un dashboard.
No generas código, generas una CONFIGURACIÓN JSON para que el backend calcule los datos.

TU TAREA:
1. Identifica qué métricas (KPIs) y gráficos responden mejor a la pregunta.
2. Decide qué operación matemática (aggregación) se necesita: contar filas, sumar valores, promedios, etc.
3. Si detectas columnas de latitud/longitud, SUGIERE un mapa.

ESTRUCTURA DE RESPUESTA (JSON ÚNICAMENTE):
{
  "title": "Título del Dashboard",
  "components": [
    {
      "id": "c1",
      "type": "kpi", 
      "title": "Ventas Totales",
      "description": "Suma total de ingresos",
      "config": {
        "operation": "sum",
        "column": "monto_venta",
        "format": "currency"
      }
    },
    {
      "id": "c2",
      "type": "chart",
      "chart_type": "bar",
      "title": "Ventas por Ciudad",
      "description": "Top 10 ciudades",
      "config": {
        "x": "ciudad",
        "y": "monto_venta",
        "operation": "sum", 
        "limit": 10
      }
    },
    {
      "id": "c3",
      "type": "map",
      "title": "Ubicación de Tiendas",
      "config": {
        "lat": "latitud",
        "lon": "longitud",
        "label": "nombre_tienda"
      }
    }
  ]
}

REGLAS DE OPERACIÓN ("operation"):
- "count": Cuenta filas (ej. número de pedidos). No requiere columna 'y'.
- "sum": Suma valores (ej. total ventas). Requiere columna 'y' numérica.
- "mean": Promedio. Requiere columna 'y' numérica.
- "none": Muestra datos crudos (solo para tablas o scatter plots).
"""

# --- UTILIDADES DE DATOS ---
def clean_dataframe(df):
    """Limpieza base para evitar errores JSON"""
    df = df.replace([np.inf, -np.inf], np.nan)
    # Convertir columnas de fecha si existen (opcional, mejora básica)
    for col in df.columns:
        if df[col].dtype == 'object':
            try:
                df[col] = pd.to_datetime(df[col])
            except:
                pass
    df = df.where(pd.notnull(df), None)
    return df

def process_component_data(df, component):
    """
    EL MOTOR: Ejecuta la lógica matemática definida en el JSON sobre el DataFrame.
    """
    try:
        c_type = component.get('type')
        config = component.get('config', {})
        
        # 1. KPI (Un solo número)
        if c_type == 'kpi':
            op = config.get('operation', 'count')
            col = config.get('column')
            
            val = 0
            if op == 'count':
                val = len(df)
            elif col and col in df.columns:
                # Asegurar numérico
                numeric_series = pd.to_numeric(df[col], errors='coerce').fillna(0)
                if op == 'sum': val = numeric_series.sum()
                elif op == 'mean': val = numeric_series.mean()
                elif op == 'max': val = numeric_series.max()
                elif op == 'min': val = numeric_series.min()
            
            return {"value": val, "label": component.get('title')}

        # 2. MAPA (Coordenadas)
        elif c_type == 'map':
            lat = config.get('lat')
            lon = config.get('lon')
            label = config.get('label')
            
            if lat in df.columns and lon in df.columns:
                # Filtramos nulos y tomamos muestra si es gigante
                cols = [lat, lon]
                if label and label in df.columns: cols.append(label)
                
                df_map = df[cols].dropna()
                # Limitamos a 1000 puntos para no matar el navegador
                if len(df_map) > 1000: df_map = df_map.sample(1000)
                
                return df_map.to_dict(orient='records')
            return []

        # 3. GRÁFICOS (Agregaciones)
        elif c_type == 'chart':
            x = config.get('x')
            y = config.get('y')
            op = config.get('operation', 'count')
            limit = config.get('limit', 20)
            
            if not x or x not in df.columns:
                return []

            # Agrupación
            if op == 'count':
                # Conteo de frecuencia (ej: cuántos registros por Categoría)
                df_res = df[x].value_counts().reset_index()
                df_res.columns = [x, 'value'] # Estandarizamos a 'value'
            
            elif y and y in df.columns:
                # Operación matemática (ej: Suma de Ventas por Categoría)
                # Asegurar que Y es numérico
                df[y] = pd.to_numeric(df[y], errors='coerce').fillna(0)
                
                if op == 'sum':
                    df_res = df.groupby(x)[y].sum().reset_index()
                elif op == 'mean':
                    df_res = df.groupby(x)[y].mean().reset_index()
                else:
                    df_res = df.groupby(x)[y].sum().reset_index() # Fallback
                
                df_res.columns = [x, 'value']
            else:
                return []

            # Ordenar y Limitar
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

def get_user_by_email(email):
    with open(USERS_FILE, 'r') as f: users = json.load(f)
    for uid, data in users.items():
        if data['email'] == email: return User(uid, data['email'], data['password'])
    return None

def save_new_user(email, password):
    with open(USERS_FILE, 'r') as f: users = json.load(f)
    for data in users.values():
        if data['email'] == email: return None
    
    uid = str(uuid.uuid4())
    pw = bcrypt.generate_password_hash(password).decode('utf-8')
    users[uid] = {'email': email, 'password': pw}
    with open(USERS_FILE, 'w') as f: json.dump(users, f)
    return User(uid, email, pw)

# --- RUTAS DE NAVEGACIÓN ---

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template("home.html")

@app.route("/auth")
def auth_page():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template("auth.html")

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)

# --- API AUTH ---

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
    user = save_new_user(data.get('email'), data.get('password'))
    if user:
        login_user(user)
        return jsonify({"message": "OK", "redirect": url_for('dashboard')})
    return jsonify({"error": "Usuario ya existe"}), 400

@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"redirect": url_for('index')})

# --- API LÓGICA DE NEGOCIO (Upload & Generate) ---

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
        
        df.columns = df.columns.str.strip()
        
        # Resumen Inteligente para el LLM
        summary = [f"Total Filas: {len(df)}"]
        col_types = {}
        for col in df.columns:
            dtype = str(df[col].dtype)
            col_types[col] = dtype
            # Enviamos muestras para que entienda el contenido
            sample = df[col].dropna().head(3).tolist()
            summary.append(f"- Columna: '{col}' (Tipo: {dtype}) | Ejemplos: {sample}")
            
        return jsonify({
            "summary": "\n".join(summary),
            "file_path": os.path.join(current_user.id, filename),
            "col_types": col_types
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/generate_dashboard", methods=["POST"])
@login_required
def generate_dashboard():
    data = request.json
    full_path = os.path.join(UPLOAD_FOLDER, data.get('file_path'))
    
    if not os.path.exists(full_path): return jsonify({"error": "Archivo no encontrado"}), 404

    try:
        # 1. Cargar DataFrame
        if full_path.endswith('.csv'): df = pd.read_csv(full_path, engine='python')
        else: df = pd.read_excel(full_path)
        df.columns = df.columns.str.strip()
        
        # 2. Consultar al LLM (Arquitecto)
        prompt = f"DATASET INFO:\n{data.get('summary')}\nSOLICITUD DEL USUARIO:\n{data.get('instruction')}"
        
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.3 # Baja temperatura para que sea riguroso con el JSON
            )
        )
        
        config_json = json.loads(response.text)
        
        # 3. Procesar Datos en Python (Ingeniero)
        processed_components = []
        for comp in config_json.get('components', []):
            # Calculamos los datos aquí
            data_result = process_component_data(df, comp)
            if data_result:
                comp['data'] = data_result # Inyectamos los datos procesados
                processed_components.append(comp)

        # 4. Guardar Resultado
        final_config = {
            "title": config_json.get('title'),
            "components": processed_components
        }

        dash_id = str(uuid.uuid4())
        user_dash_dir = os.path.join(DASHBOARD_DIR, current_user.id)
        os.makedirs(user_dash_dir, exist_ok=True)
        
        with open(os.path.join(user_dash_dir, f"{dash_id}.json"), 'w') as f:
            json.dump({
                "id": dash_id,
                "created_at": datetime.now().isoformat(),
                "config": final_config,
                "file_path": data.get('file_path')
            }, f)

        return jsonify(final_config)

    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"error": str(e)}), 500

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
                    # Safe get
                    title = d.get('config', {}).get('title', 'Sin título')
                    items.append({"id": d['id'], "title": title, "created_at": d.get('created_at')})
            except: pass
    items.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(items)

@app.route("/api/dashboards/<dash_id>", methods=["GET"]) 
@login_required
def get_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return jsonify({"error": "No existe"}), 404
    
    with open(path) as f: dash_data = json.load(f)
    
    # Nota: Ya guardamos los datos procesados en dash_data['config']
    # así que no hace falta volver a leer el CSV, lo que hace la carga INSTANTÁNEA.
    return jsonify(dash_data['config'])

@app.route("/api/dashboards/<dash_id>", methods=["DELETE"])
@login_required
def delete_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return jsonify({"message": "Eliminado"})
    return jsonify({"error": "No encontrado"}), 404

if __name__ == "__main__":
    app.run(debug=True, port=5000)