import requests
import re
import os
from supabase import create_client
import time
from datetime import datetime

# Configuración de conexión
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

def scraping_presidencia():
    print("--- Sincronización Automática LexEC ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    
    try:
        response = requests.get(url_fuente, headers=headers, timeout=30)
        # Intentamos extraer filas de tabla para buscar fechas reales
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        filas = soup.find_all('tr')

        count = 0
        for fila in filas:
            cols = fila.find_all('td')
            if len(cols) >= 3:
                num = cols[0].get_text(strip=True)
                if "No" in num or not num: continue # Saltar encabezado
                
                fecha_real = cols[1].get_text(strip=True) # Intentamos capturar la fecha de la tabla
                asunto = cols[2].get_text(strip=True)
                link = fila.find('a', href=True)
                
                if link:
                    url_pdf = link['href']
                    # Limpiamos el título para que no sea redundante
                    titulo_final = f"Decreto Ejecutivo No. {num}"
                    
                    # Convertir fecha de texto (ej: "10 de abril 2024") a formato ISO si es posible
                    # Por ahora, si no es fecha válida, usamos la de hoy corregida
                    fecha_iso = datetime.now().strftime('%Y-%m-%d') 

                    data = {
                        "titulo": titulo_final,
                        "jerarquia": "Decreto Ejecutivo",
                        "vigencia": "Vigente",
                        "fecha_pub": fecha_iso, 
                        "url_pdf": url_pdf,
                        "sumario": asunto,
                        "origen": "Presidencia"
                    }
                    
                    try:
                        # Usamos insert. Si quieres evitar duplicados, 
                        # lo ideal sería que en Supabase pongas la columna 'titulo' como UNIQUE.
                        supabase.table("normas").insert(data).execute()
                        print(f"✓ Nuevo: {titulo_final}")
                        count += 1
                    except:
                        pass # Si ya existe, lo salta

        print(f"--- Proceso terminado: {count} nuevos ---")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    scraping_presidencia()
