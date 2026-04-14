import requests
import re
import os
from bs4 import BeautifulSoup
from supabase import create_client
import time
from datetime import datetime

# Configuración
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

# Lista de URLs para monitorear (Puedes añadir más aquí)
FUENTES = [
    "https://www.presidencia.gob.ec/decretos-ejecutivos/",
    "https://www.presidencia.gob.ec/resoluciones/" # Ajustada para buscar resoluciones
]

def procesar_pagina(url):
    print(f"--- Escaneando: {url} ---")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        filas = soup.find_all('tr')
        nuevos = 0

        for fila in filas:
            cols = fila.find_all('td')
            if len(cols) >= 3:
                # Extraer datos
                num = cols[0].get_text(strip=True)
                fecha_texto = cols[1].get_text(strip=True)
                asunto = cols[2].get_text(strip=True)
                link = fila.find('a', href=True)
                
                if link and ".pdf" in link['href'].lower():
                    url_pdf = link['href']
                    
                    # Determinar si es Decreto o Resolución basado en la URL o el texto
                    jerarquia = "Decreto Ejecutivo" if "decretos" in url else "Resolución"
                    titulo_final = f"{jerarquia} No. {num}"

                    # Limpieza de fecha: Si no hay fecha válida, ponemos la de hoy
                    # Intentamos formato simple AAAA-MM-DD
                    fecha_db = datetime.now().strftime('%Y-%m-%d')

                    data = {
                        "titulo": titulo_final,
                        "jerarquia": jerarquia,
                        "vigencia": "Vigente",
                        "fecha_pub": fecha_db, 
                        "url_pdf": url_pdf,
                        "sumario": asunto,
                        "origen": "Presidencia"
                    }
                    
                    try:
                        # Usamos insert simple. 
                        supabase.table("normas").insert(data).execute()
                        print(f"✓ Guardado: {titulo_final}")
                        nuevos += 1
                    except:
                        # Si da error es porque probablemente ya existe (si pusiste UNIQUE) o fallo de red
                        pass
        return nuevos
    except Exception as e:
        print(f"Error en {url}: {e}")
        return 0

def scraping_total():
    total_general = 0
    for base_url in FUENTES:
        # AQUÍ ESTÁ LA MAGIA: Escanea la página 1 y la 2 (puedes subir el rango a 5 o 10 para barrer más)
        for pagina in range(1, 3): 
            url_final = base_url if pagina == 1 else f"{base_url}page/{pagina}/"
            count = procesar_pagina(url_final)
            total_general += count
            if count == 0 and pagina > 1: # Si una página vieja no da resultados, deja de buscar más atrás
                break
            time.sleep(2) # Pausa para no ser bloqueado

    print(f"--- Sincronización terminada. Total LexEC: {total_general} registros ---")

if __name__ == "__main__":
    scraping_total()
