import requests
from bs4 import BeautifulSoup
import os
from supabase import create_client
import time

# Configuración de conexión
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

def scraping_presidencia():
    print("--- Iniciando Sincronización LexEC (Protocolo de Emergencia) ---")
    
    # Intentaremos con la URL de archivos directamente
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    # Cabeceras simulando un iPhone (los servidores suelen ser menos estrictos con móviles)
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-EC,es;q=0.9',
        'Referer': 'https://www.google.com.ec/',
        'Connection': 'keep-alive',
    }
    
    try:
        # Usamos un tiempo de espera más largo y permitimos redirecciones
        response = requests.get(url_fuente, headers=headers, timeout=45, allow_redirects=True)
        
        if response.status_code != 200:
            print(f"Bloqueo detectado: Código {response.status_code}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Si no hay tabla, buscamos CUALQUIER enlace que diga "Decreto" y sea ".pdf"
        enlaces_encontrados = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            texto = a.get_text().strip().lower()
            
            if ".pdf" in href.lower() and ("decreto" in texto or "dec" in texto or "ejecutivo" in texto):
                enlaces_encontrados.append({
                    "url": href,
                    "texto": a.get_text().strip()
                })

        if not enlaces_encontrados:
            print("El servidor sigue ocultando el contenido. Intentando extracción de respaldo...")
            # Plan C: Buscar en los metadatos de la página
            if "decreto" in response.text.lower():
                print("Se detectó la palabra 'decreto' en el código, pero los enlaces están ocultos.")
            else:
                print("Error: Página totalmente protegida contra bots de GitHub.")
            return

        print(f"Se localizaron {len(enlaces_encontrados)} documentos. Sincronizando...")

        for item in enlaces_encontrados:
            # Intentar extraer un número de decreto del texto o la URL
            titulo_final = item['texto'] if len(item['texto']) > 5 else f"Decreto Ejecutivo (Ref: {item['url'].split('/')[-1]})"
            
            data = {
                "titulo": titulo_final,
                "resumen": "Documento oficial de la Presidencia de la República.",
                "tipo": "Decreto Ejecutivo",
                "fecha": "Reciente",
                "url_pdf": item['url'],
                "institucion": "Presidencia de la República",
                "estado": "Vigente"
            }
            
            try:
                supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                print(f"✓ Sincronizado: {titulo_final[:50]}...")
            except Exception as e:
                print(f"Error al guardar: {e}")
            
            time.sleep(1)

    except Exception as e:
        print(f"Falla técnica: {e}")

if __name__ == "__main__":
    scraping_presidencia()
