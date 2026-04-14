import requests
import re
import os
from supabase import create_client
import time

# Configuración de conexión
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

def scraping_presidencia():
    print("--- Sincronización LexEC (Protocolo de Mínimos) ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url_fuente, headers=headers, timeout=30)
        html = response.text

        patron = re.compile(r'href="(https?://[^"]+\.pdf)"[^>]*>(.*?)</a>', re.IGNORECASE)
        enlaces = patron.findall(html)

        if not enlaces:
            print("No se encontraron enlaces.")
            return

        print(f"Detectados {len(enlaces)} documentos. Guardando solo campos esenciales...")

        count = 0
        for url_pdf, texto_sucio in enlaces:
            texto_limpio = re.sub(r'<[^>]+>', '', texto_sucio).strip()
            
            if len(texto_limpio) < 3:
                titulo_final = f"Decreto Ejecutivo {url_pdf.split('/')[-1]}"
            else:
                titulo_final = texto_limpio

            # ENVIAMOS EL MÍNIMO ABSOLUTO DE COLUMNAS
            # Según tus imágenes anteriores, estas son las que SIEMPRE están
            data = {
                "titulo": titulo_final,
                "url_pdf": url_pdf,
                "tipo": "Decreto Ejecutivo",
                "institucion": "Presidencia de la República"
            }
            
            try:
                supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                print(f"✓ ÉXITO: {titulo_final[:30]}...")
                count += 1
            except Exception as e:
                print(f"x Error: Supabase rechazó los campos. Detalle: {e}")
            
            time.sleep(0.5)

        print(f"--- Sincronización terminada: {count} cargados ---")

    except Exception as e:
        print(f"Error técnico: {e}")

if __name__ == "__main__":
    scraping_presidencia()
