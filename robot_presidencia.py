import requests
import re
import os
from bs4 import BeautifulSoup
from supabase import create_client
import time
from datetime import datetime

# Conexión
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

FUENTES = [
    "https://www.presidencia.gob.ec/decretos-ejecutivos/",
    "https://www.presidencia.gob.ec/resoluciones/"
]

def limpiar_fecha(texto_fecha):
    """Convierte '10 de abril 2024' a '2024-04-10'"""
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    try:
        texto_fecha = texto_fecha.lower()
        partes = re.findall(r'\w+', texto_fecha) # Extrae números y palabras
        if len(partes) >= 3:
            dia = partes[0].zfill(2)
            mes = meses.get(partes[2], '01') # partes[1] suele ser 'de'
            anio = partes[-1]
            return f"{anio}-{mes}-{dia}"
    except:
        pass
    return datetime.now().strftime('%Y-%m-%d')

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
                num = cols[0].get_text(strip=True)
                fecha_raw = cols[1].get_text(strip=True)
                asunto = cols[2].get_text(strip=True)
                link = fila.find('a', href=True)
                
                if link and ".pdf" in link['href'].lower():
                    url_pdf = link['href']
                    jerarquia = "Decreto Ejecutivo" if "decretos" in url else "Resolución"
                    
                    # Limpiamos el título para que no se repita "Decreto Ejecutivo No. Decreto..."
                    num_limpio = num.replace("Decreto Ejecutivo", "").replace("No.", "").strip()
                    titulo_final = f"{jerarquia} No. {num_limpio}"
                    
                    fecha_iso = limpiar_fecha(fecha_raw)

                    data = {
                        "titulo": titulo_final,
                        "jerarquia": jerarquia,
                        "vigencia": "Vigente",
                        "fecha_pub": fecha_iso, 
                        "url_pdf": url_pdf,
                        "sumario": asunto,
                        "origen": "Presidencia"
                    }
                    
                    try:
                        # Si quieres evitar que el log diga error, podrías consultar antes si existe,
                        # pero el insert simple es más rápido.
                        supabase.table("normas").insert(data).execute()
                        print(f"✓ Guardado: {titulo_final} ({fecha_iso})")
                        nuevos += 1
                    except:
                        continue 
        return nuevos
    except Exception as e:
        print(f"Error: {e}")
        return 0

if __name__ == "__main__":
    for base_url in FUENTES:
        # Escaneamos 3 páginas de cada fuente para tener historial
        for p in range(1, 4):
            u = base_url if p == 1 else f"{base_url}page/{p}/"
            res = procesar_pagina(u)
            if res == 0 and p > 1: break 
            time.sleep(1)
