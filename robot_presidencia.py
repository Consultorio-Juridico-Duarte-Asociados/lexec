import requests
from bs4 import BeautifulSoup
import os
from supabase import create_client

# Configuración de conexión
url_supabase = os.environ.get("SUPABASE_URL")
key_supabase = os.environ.get("SUPABASE_SERVICE_KEY")
supabase = create_client(url_supabase, key_supabase)

def scraping_presidencia():
    print("Iniciando búsqueda de Decretos...")
    url_fuente = "https://www.presidencia.gob.ec/decretos-ejecutivos/"
    
    try:
        # User-agent para evitar bloqueos básicos
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url_fuente, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        tabla = soup.find('table') 
        if not tabla:
            print("No se encontró la tabla en la página.")
            return

        filas = tabla.find_all('tr')[1:] # Saltamos encabezado

        for fila in filas:
            cols = fila.find_all('td')
            if len(cols) >= 4:
                num = cols[0].text.strip()
                fec = cols[1].text.strip()
                asunto = cols[2].text.strip()
                link = cols[3].find('a')['href'] if cols[3].find('a') else None

                if link:
                    data = {
                        "titulo": f"Decreto Ejecutivo No. {num}",
                        "resumen": asunto,
                        "tipo": "Decreto Ejecutivo",
                        "fecha": fec,
                        "url_pdf": link,
                        "institucion": "Presidencia de la República",
                        "estado": "Vigente"
                    }
                    
                    # Usamos upsert para no duplicar si el decreto ya existe
                    supabase.table("normas").upsert(data, on_conflict="titulo").execute()
                    print(f"Procesado: Decreto {num}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    scraping_presidencia()
