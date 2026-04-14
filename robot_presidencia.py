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
    print("--- Sincronización LexEC (Modo Captura Total) ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url_fuente, headers=headers, timeout=30)
        html = response.text

        # Este patrón busca cualquier enlace PDF sin importar el texto que tenga
        # Captura: 1. La URL del PDF y 2. El texto del enlace
        patron = re.compile(r'href="(https?://[^"]+\.pdf)"[^>]*>(.*?)</a>', re.IGNORECASE)
        enlaces = patron.findall(html)

        if not enlaces:
            print("No se encontraron enlaces PDF. El sitio podría estar usando un visor externo.")
            return

        print(f"Se detectaron {len(enlaces)} documentos. Guardando todos...")

        count = 0
        for url_pdf, texto_sucio in enlaces:
            # Limpiamos el texto de etiquetas HTML como <strong> o <span>
            texto_limpio = re.sub(r'<[^>]+>', '', texto_sucio).strip()
            
            # Si el texto es muy corto o vacío, usamos el nombre del archivo como título
            if len(texto_limpio) < 3:
                nombre_archivo = url_pdf.split('/')[-1].replace('.pdf', '')
                titulo_final = f"Decreto Ejecutivo {nombre_archivo}"
            else:
                titulo_final = texto_limpio

            data = {
                "titulo": titulo_final,
                "resumen": f"Documento oficial localizado en el portal de la Presidencia: {titulo_final}",
                "tipo": "Decreto Ejecutivo",
                "fecha": "2026", 
                "url_pdf": url_pdf,
                "institucion": "Presidencia de la República",
                "estado": "Vigente"
            }
            
            try:
                # Intentamos guardar
                supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                print(f"✓ Guardado: {titulo_final}")
                count += 1
            except Exception as e:
                print(f"x Error al insertar {titulo_final}: {e}")
            
            time.sleep(0.5)

        print(f"--- Proceso terminado. {count} documentos en base de datos ---")

    except Exception as e:
        print(f"Error técnico: {e}")

if __name__ == "__main__":
    scraping_presidencia()
