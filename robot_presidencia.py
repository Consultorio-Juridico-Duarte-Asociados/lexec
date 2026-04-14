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
    print("--- Sincronización LexEC (Versión Compatibilidad Total) ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url_fuente, headers=headers, timeout=30)
        html = response.text

        # Buscamos enlaces PDF
        patron = re.compile(r'href="(https?://[^"]+\.pdf)"[^>]*>(.*?)</a>', re.IGNORECASE)
        enlaces = patron.findall(html)

        if not enlaces:
            print("No se encontraron enlaces PDF.")
            return

        print(f"Se detectaron {len(enlaces)} documentos. Intentando guardado simplificado...")

        count = 0
        for url_pdf, texto_sucio in enlaces:
            texto_limpio = re.sub(r'<[^>]+>', '', texto_sucio).strip()
            
            if len(texto_limpio) < 3:
                nombre_archivo = url_pdf.split('/')[-1].replace('.pdf', '').replace('_', ' ')
                titulo_final = f"Decreto Ejecutivo {nombre_archivo}"
            else:
                titulo_final = texto_limpio

            # ENVIAMOS SOLO LO ESENCIAL PARA EVITAR ERRORES DE COLUMNAS FALTANTES
            data = {
                "titulo": titulo_final,
                "resumen": f"Documento oficial: {titulo_final}",
                "tipo": "Decreto Ejecutivo",
                "fecha": "2026", 
                "url_pdf": url_pdf,
                "institucion": "Presidencia de la República"
                # HE QUITADO LA COLUMNA 'ESTADO' QUE DABA ERROR
            }
            
            try:
                supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                print(f"✓ ÉXITO: {titulo_final[:40]}...")
                count += 1
            except Exception as e:
                print(f"x Error en base de datos: {e}")
            
            time.sleep(0.5)

        print(f"--- Sincronización terminada. {count} documentos cargados con éxito ---")

    except Exception as e:
        print(f"Error técnico: {e}")

if __name__ == "__main__":
    scraping_presidencia()
