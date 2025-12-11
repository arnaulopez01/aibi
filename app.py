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
app.secret_key = os.getenv("SECRET_KEY", "dev_secret_key") # Cambiar en producción
bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth_page' # Redirige aquí si intentan entrar al dashboard sin login

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

SYSTEM_PROMPT = """
Eres un experto en Visualización de Datos con Apache ECharts.
Tu objetivo es analizar un dataset y generar una configuración JSON para 3 gráficos.
Devuelve UNICAMENTE JSON válido.
ESTRUCTURA: { "dashboard_title": "...", "charts": [{ "id": "...", "title": "...", "type": "bar", "x_column": "...", "y_column": "...", "description": "..." }] }
"""

# --- UTILIDADES ---
def clean_dataframe(df):
    """Limpieza robusta para evitar NaN en JSON"""
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.astype(object)
    df = df.where(pd.notnull(df), None)
    return df

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
    # Si ya está logueado, directo al dashboard
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
        df = clean_dataframe(df)

        # Resumen
        summary = [f"Filas: {len(df)}"]
        col_types = {}
        df_infer = df.copy().infer_objects()
        for col in df.columns:
            dtype = str(df_infer[col].dtype)
            col_types[col] = dtype
            sample = df[col].dropna().head(3).tolist()
            summary.append(f"- {col} ({dtype}): {sample}")
            
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
        if full_path.endswith('.csv'): df = pd.read_csv(full_path, engine='python')
        else: df = pd.read_excel(full_path)
        
        df.columns = df.columns.str.strip()
        df = clean_dataframe(df)
        
        prompt = f"DATASET:\n{data.get('summary')}\nUSUARIO:\n{data.get('instruction')}"
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        
        config = json.loads(response.text)
        
        # Guardar Dashboard
        dash_id = str(uuid.uuid4())
        user_dash_dir = os.path.join(DASHBOARD_DIR, current_user.id)
        os.makedirs(user_dash_dir, exist_ok=True)
        
        with open(os.path.join(user_dash_dir, f"{dash_id}.json"), 'w') as f:
            json.dump({
                "id": dash_id,
                "created_at": datetime.now().isoformat(),
                "title": config.get("dashboard_title"),
                "config": config,
                "file_path": data.get('file_path')
            }, f)

        return jsonify({
            "config": config,
            "data": df.to_dict(orient='records'),
            "col_types": data.get('col_types', {})
        })
    except Exception as e:
        print(e)
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
                    items.append({"id": d['id'], "title": d.get('title'), "created_at": d.get('created_at')})
            except: pass
    items.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(items)

@app.route("/api/dashboards/<dash_id>", methods=["DELETE"])
@login_required
def delete_dashboard(dash_id):
    # Ruta segura al archivo del dashboard
    user_dash_dir = os.path.join(DASHBOARD_DIR, current_user.id)
    file_path = os.path.join(user_dash_dir, f"{dash_id}.json")
    
    if os.path.exists(file_path):
        try:
            os.remove(file_path) # Borra el archivo .json
            return jsonify({"message": "Dashboard eliminado correctamente"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "Dashboard no encontrado"}), 404
@login_required
def get_dashboard(dash_id):
    path = os.path.join(DASHBOARD_DIR, current_user.id, f"{dash_id}.json")
    if not os.path.exists(path): return jsonify({"error": "No existe"}), 404
    
    with open(path) as f: dash_data = json.load(f)
    
    file_path = os.path.join(UPLOAD_FOLDER, dash_data['file_path'])
    if os.path.exists(file_path):
        if file_path.endswith('.csv'): df = pd.read_csv(file_path, engine='python')
        else: df = pd.read_excel(file_path)
        df.columns = df.columns.str.strip()
        df = clean_dataframe(df)
        records = df.to_dict(orient='records')
        col_types = {col: str(t) for col, t in df.infer_objects().dtypes.items()}
    else:
        records, col_types = [], {}

    return jsonify({"config": dash_data['config'], "data": records, "col_types": col_types})

if __name__ == "__main__":
    app.run(debug=True, port=5000)