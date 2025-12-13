import json
import uuid
import os
from flask import Flask
from flask_bcrypt import Bcrypt

# Configuración mínima para usar Bcrypt
app = Flask(__name__)
bcrypt = Bcrypt(app)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def create_admin():
    print("--- CREAR USUARIO ADMINISTRADOR ---")
    email = input("Email: ")
    password = input("Contraseña: ")

    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f: json.dump({}, f)

    with open(USERS_FILE, 'r') as f: 
        users = json.load(f)

    # Verificar si existe
    for uid, data in users.items():
        if data['email'] == email:
            print("¡Error! Ese email ya existe.")
            return

    # Crear usuario
    uid = str(uuid.uuid4())
    pw_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    users[uid] = {'email': email, 'password': pw_hash}
    
    with open(USERS_FILE, 'w') as f: 
        json.dump(users, f)
    
    print(f"✅ Usuario {email} creado exitosamente.")

if __name__ == "__main__":
    create_admin()