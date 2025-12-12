import os
import requests
import json
from dotenv import load_dotenv

# Carga la clave del .env
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ ERROR: No se encontró GEMINI_API_KEY en el archivo .env")
    exit()

print("📡 Conectando directamente a la API de Google...")

# URL directa de la API (v1beta)
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

try:
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print("\n✅ LISTA DE MODELOS DISPONIBLES (Copia uno de estos):")
        print("="*50)
        
        found_any = False
        for m in data.get('models', []):
            # Limpiamos el nombre (quita 'models/' del principio)
            name = m.get('name', '').replace('models/', '')
            
            # Filtramos solo los que sirven para chat (generateContent)
            methods = m.get('supportedGenerationMethods', [])
            if 'generateContent' in methods:
                print(f"👉 {name}")
                found_any = True
        
        print("="*50)
        
        if not found_any:
            print("⚠️ No se encontraron modelos compatibles con Chat.")
    else:
        print(f"❌ Error HTTP {response.status_code}:")
        print(response.text)

except Exception as e:
    print(f"❌ Error de conexión: {e}")