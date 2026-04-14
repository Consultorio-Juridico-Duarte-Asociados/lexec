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
    print("--- Sincronización LexEC (Configuración Final Basada en Metadata) ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url_fuente, headers=headers, timeout=30)
        html = response.text

        # Radar para buscar los PDF y sus nombres
        patron = re.compile(r'href="(https?://[^"]+\.pdf)"[^>]*>(.*?)</a>', re.IGNORECASE)
        enlaces = patron.findall(html)

        if not enlaces:
            print("No se encontraron documentos en la página.")
            return

        print(f"Detectados {len(enlaces)} documentos. Procesando para LexEC...")

        count = 0
        fecha_hoy = datetime.now().strftime('%Y-%m-%d') # Fecha requerida por tu columna date

        for url_pdf, texto_sucio in enlaces:
            texto_limpio = re.sub(r'<[^>]+>', '', texto_sucio).strip()
            
            # Limpieza de título
            if len(texto_limpio) < 5:
                nombre_archivo = url_pdf.split('/')[-1].replace('.pdf', '').replace('-', ' ')
                titulo_final = f"Decreto Ejecutivo {nombre_archivo}"
            else:
                titulo_final = texto_limpio

            # MAPEO EXACTO DE TUS COLUMNAS SEGÚN EL CSV
            data = {
                "titulo": titulo_final,
                "jerarquia": "Decreto Ejecutivo", # Obligatorio (NO NULL)
                "vigencia": "Vigente",           # Obligatorio (NO NULL)
                "fecha_pub": fecha_hoy,          # Obligatorio (NO NULL) - Formato date
                "url_pdf": url_pdf,
                "sumario": f"Documento oficial de la Presidencia de la República: {titulo_final}",
                "origen": "Presidencia"
            }
            
            try:
                # El upsert usa 'titulo' para no duplicar
                supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                print(f"✓ Sincronizado: {titulo_final[:50]}...")
                count += 1
            except Exception as e:
                print(f"x Error en Supabase para {titulo_final[:20]}: {e}")
            
            time.sleep(1)

        print(f"--- Sincronización terminada: {count} documentos cargados ---")

    except Exception as e:
        print(f"Error técnico: {e}")

if __name__ == "__main__":
    scraping_presidencia()
