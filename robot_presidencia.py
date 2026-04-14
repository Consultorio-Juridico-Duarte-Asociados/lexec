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
    print("--- Iniciando Sincronización LexEC (Protocolo de Extracción Profunda) ---")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url_fuente, headers=headers, timeout=30)
        html_completo = response.text

        # Usamos Expresiones Regulares para cazar los enlaces PDF y los números de decreto
        # Aunque la tabla no se "dibuje", el enlace suele estar en el código fuente
        patron = re.compile(r'href="(https?://[^"]+\.pdf)"[^>]*>(.*?)</a>', re.IGNORECASE)
        enlaces = patron.findall(html_completo)

        if not enlaces:
            print("No se encontraron enlaces PDF mediante patrones directos.")
            return

        print(f"Se detectaron {len(enlaces)} posibles documentos. Filtrando decretos...")

        count = 0
        for url_pdf, texto in enlaces:
            texto_limpio = texto.replace('<strong>', '').replace('</strong>', '').strip()
            
            # Solo nos interesan enlaces que mencionen "decreto" o tengan números
            if "decreto" in texto_limpio.lower() or "dec" in texto_limpio.lower() or any(char.isdigit() for char in texto_limpio):
                
                # Intentamos extraer un número para el título
                num_match = re.search(r'\d+', texto_limpio)
                num = num_match.group() if num_match else "Nuevo"
                
                data = {
                    "titulo": f"Decreto Ejecutivo No. {num}",
                    "resumen": texto_limpio if len(texto_limpio) > 10 else "Documento oficial de la Presidencia.",
                    "tipo": "Decreto Ejecutivo",
                    "fecha": "2026", # Fecha aproximada
                    "url_pdf": url_pdf,
                    "institucion": "Presidencia de la República",
                    "estado": "Vigente"
                }
                
                try:
                    supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                    print(f"✓ Sincronizado: Decreto {num}")
                    count += 1
                except Exception as e:
                    pass # Evitamos que un error de uno detenga el resto
                
                time.sleep(0.5)

        print(f"--- Sincronización terminada. {count} decretos procesados ---")

    except Exception as e:
        print(f"Error técnico: {e}")

if __name__ == "__main__":
    scraping_presidencia()
