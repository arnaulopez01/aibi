import os
import json
import uuid
import time
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from google import genai
from google.genai import types

# IMPORTAMOS EL MÓDULO DE LÓGICA
from insights import clean_dataframe, apply_global_filters, process_component_data

load_dotenv()

# --- CONFIGURACIÓN BÁSICA ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_secret_key_super_segura")
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth_page'

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
MODEL_NAME = "gemini-2.5-flash" 
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# --- PROMPT MAESTRO ACTUALIZADO ---
SYSTEM_PROMPT = """
Eres un Director de Business Intelligence experto.
Tu objetivo es crear un dashboard de alto impacto basado en un dataset.

TU MISIÓN OBLIGATORIA:
Genera un JSON con la siguiente estructura EXACTA de componentes (en este orden):

1. **KPI 1 (Numérico):** El indicador más importante (ej: Ingresos Totales, Cantidad Neta).
2. **KPI 2 (Numérico):** Un indicador secundario o promedio relevante (ej: Ticket Medio, Coste Promedio).
3. **GRÁFICO DE BARRAS:** Para comparar categorías principales (Top productos, Ventas por Vendedor, etc).
4. **GRÁFICO CIRCULAR (PIE):** Para mostrar distribución o proporción (Share de mercado, Estado de pedidos).
5. **MAPA (Solo si aplica):** SI Y SOLO SI detectas columnas de Latitud y Longitud, añade un quinto componente tipo "map". Si no hay coordenadas claras, NO lo incluyas.

REGLAS DE ORO PARA TÍTULOS:
- Usa lenguaje de negocio, NO nombres de columnas (ej: NO USAR "sum_ventas", USAR "Ventas Totales").
- **IMPRESCINDIBLE:** Intenta deducir la unidad y ponla en el título entre paréntesis.
  - Ej: "Capacidad de Almacenamiento (Litros)"
  - Ej: "Facturación Global (EUR)"
  - Ej: "Tiempo de Entrega (Días)"
  - Ej: "Peso Total (kg)"

ESTRUCTURA JSON DE RESPUESTA:
{
  "title": "Título del Dashboard (basado en el nombre del archivo)",
  "components": [
    {
      "id": "kpi1",
      "type": "kpi", 
      "title": "Ingresos Totales (USD)",
      "description": "Facturación acumulada del periodo",
      "config": { "operation": "sum", "column": "amount" }
    },
    {
      "id": "kpi2",
      "type": "kpi", 
      "title": "Precio Promedio (USD)",
      "config": { "operation": "mean", "column": "price" }
    },
    {
      "id": "chart1",
      "type": "chart",
      "chart_type": "bar", 
      "title": "Top 10 Productos por Ventas (Unidades)",
      "config": { "x": "product_name", "y": "quantity", "operation": "sum", "limit": 10 }
    },
    {
      "id": "chart2",
      "type": "chart",
      "chart_type": "pie", 
      "title": "Distribución por Categoría (%)",
      "config": { "x": "category", "y": "quantity", "operation": "sum" }
    },
    {
      "id": "map1",
      "type": "map",
      "title": "Ubicación de Clientes",
      "config": { "lat": "latitude", "lon": "longitude", "label": "store_name" }
    }
  ]
}
"""

# ... [CLASES Y FUNCIONES DE USUARIO SE MANTIENEN IGUAL] ...
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
    for uid, data in users.items():
        if data['email'] == email: return User(uid, data['email'], data['password'])
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

# --- RUTAS PRINCIPALES ---

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

@app.route("/view/<dash_id>")
@login_required
def view_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return "Dashboard no encontrado", 404
    return render_template("share.html", dash_id=dash_id)

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
    if get_user_by_email(data.get('email')): return jsonify({"error": "Usuario ya existe"}), 400
    user = save_new_user(data.get('email'), data.get('password'))
    login_user(user)
    return jsonify({"message": "OK", "redirect": url_for('dashboard')})

@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"redirect": url_for('index')})

# --- LÓGICA CORE ---

@app.route("/upload_and_analyze", methods=["POST"])
@login_required
def upload_and_analyze():
    if 'file' not in request.files: return jsonify({"error": "Falta archivo"}), 400
    file = request.files['file']
    
    user_path = os.path.join(UPLOAD_FOLDER, current_user.id)
    os.makedirs(user_path, exist_ok=True)
    # Guardamos nombre original para contexto
    original_name = file.filename
    filename = f"{uuid.uuid4().hex[:8]}_{original_name}"
    filepath = os.path.join(user_path, filename)
    file.save(filepath)

    try:
        if filename.endswith('.csv'): df = pd.read_csv(filepath, engine='python')
        else: df = pd.read_excel(filepath)
        df.columns = df.columns.str.strip()
        
        df = clean_dataframe(df)
        
        summary = [f"Archivo: {original_name}", f"Registros: {len(df)}"]
        for col in df.columns:
            dtype = str(df[col].dtype)
            sample = [str(x)[:40] for x in df[col].dropna().head(3).tolist()]
            summary.append(f"- '{col}' ({dtype}): Ejemplo: {sample}")
            
        return jsonify({
            "summary": "\n".join(summary),
            "file_path": os.path.join(current_user.id, filename),
            "original_name": original_name # Enviamos nombre limpio al front
        })
    except Exception as e:
        return jsonify({"error": f"Error leyendo archivo: {str(e)}"}), 500

@app.route("/generate_dashboard", methods=["POST"])
@login_required
def generate_dashboard():
    if not client: return jsonify({"error": "Error Servidor: Falta GEMINI_API_KEY"}), 500

    data = request.json
    full_path = os.path.join(UPLOAD_FOLDER, data.get('file_path'))
    
    # Recuperamos el nombre original del archivo para dárselo a la IA
    # Si viene del front perfecto, si no, intentamos limpiarlo del path
    filename_context = data.get('original_name', os.path.basename(full_path).split('_', 1)[-1])

    if not os.path.exists(full_path): return jsonify({"error": "Archivo perdido"}), 404

    try:
        if full_path.endswith('.csv'): df = pd.read_csv(full_path, engine='python')
        else: df = pd.read_excel(full_path)
        df.columns = df.columns.str.strip()

        # Construimos el Prompt enriquecido
        prompt = (
            f"NOMBRE DEL ARCHIVO: {filename_context}\n"
            f"RESUMEN DE COLUMNAS Y DATOS:\n{data.get('summary')}\n"
            f"INTENCIÓN DEL USUARIO: {data.get('instruction')}\n"
            "Recuerda: 2 KPIs, 1 Barra, 1 Pie y Mapa (si hay coords)."
        )
        
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
                time.sleep(1.5 ** attempt)

        config_json = json.loads(response.text)

        processed_components = []
        for comp in config_json.get('components', []):
            comp_data = process_component_data(df, comp)
            if comp_data:
                comp['data'] = comp_data
                processed_components.append(comp)

        final_config = {
            "title": config_json.get('title', f"Dashboard: {filename_context}"),
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
        print(f"Error GenAI: {e}")
        return jsonify({"error": str(e)}), 500

# --- RUTAS GESTIÓN Y FILTROS ---

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

@app.route("/api/dashboards/<dash_id>/filter", methods=["POST"])
@login_required
def filter_dashboard(dash_id):
    filters = request.json.get('filters', {})
    
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return jsonify({"error": "Error carga"}), 404
    
    with open(path) as f: dash_data = json.load(f)
    
    full_path = os.path.join(UPLOAD_FOLDER, dash_data['file_path'])
    if full_path.endswith('.csv'): df = pd.read_csv(full_path, engine='python')
    else: df = pd.read_excel(full_path)
    df.columns = df.columns.str.strip()
    
    df_filtered = apply_global_filters(df, filters)
    
    updated_components = []
    for comp in dash_data['config']['components']:
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