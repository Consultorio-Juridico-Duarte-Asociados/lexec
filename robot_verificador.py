#!/usr/bin/env python3
"""
LexEC Robot Verificador y Actualizador
- Verifica si las normas en Supabase están actualizadas
- Busca PDFs más recientes en fuentes oficiales
- Actualiza estado y url_pdf cuando encuentra versión nueva
- Corre desde GitHub Actions
"""

import os, re, json, time, hashlib
from datetime import datetime, date
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}

# ── Base de reformas conocidas ─────────────────────────────────────────────────
# Cada entrada: codigo (busca en codigo_unico), titulo_contiene,
# fecha_ultima_reforma, ultimo_ro, url_pdf_actualizado, descripcion
REFORMAS = [
    {
        "codigo": "CONST",
        "titulo_contiene": "constitución",
        "fecha_reforma": "2024-05-30",
        "ultimo_ro": "Tercer Suplemento RO 568, 30-V-2024",
        "url_pdf": "https://www.oas.org/juridico/mla/sp/ecu/sp_ecu-int-text-const.pdf",
        "descripcion": "Última reforma constitucional — RO 568 Tercer Suplemento 2024"
    },
    {
        "codigo": "COIP",
        "titulo_contiene": "código orgánico integral penal",
        "fecha_reforma": "2023-09-21",
        "ultimo_ro": "Segundo Suplemento RO 385, 21-IX-2023",
        "url_pdf": "https://www.defensa.gob.ec/wp-content/uploads/downloads/2023/09/COIP-reformado-2023.pdf",
        "descripcion": "Reforma COIP — Ley de Seguridad Ciudadana 2023"
    },
    {
        "codigo": "COGEP",
        "titulo_contiene": "código orgánico general de procesos",
        "fecha_reforma": "2023-02-22",
        "ultimo_ro": "Suplemento RO 235, 22-II-2023",
        "url_pdf": "",
        "descripcion": "Reforma COGEP 2023 — ajustes al proceso civil"
    },
    {
        "codigo": "COOTAD",
        "titulo_contiene": "organización territorial",
        "fecha_reforma": "2023-10-18",
        "ultimo_ro": "Suplemento RO 410, 18-X-2023",
        "url_pdf": "",
        "descripcion": "Reforma COOTAD 2023"
    },
    {
        "codigo": "LOSNCP",
        "titulo_contiene": "contratación pública",
        "fecha_reforma": "2023-10-17",
        "ultimo_ro": "Suplemento RO 408, 17-X-2023",
        "url_pdf": "",
        "descripcion": "Reforma Ley Orgánica del Sistema Nacional de Contratación Pública 2023"
    },
    {
        "codigo": "LOSEP",
        "titulo_contiene": "servicio público",
        "fecha_reforma": "2024-03-14",
        "ultimo_ro": "Suplemento RO 510, 14-III-2024",
        "url_pdf": "",
        "descripcion": "Reforma LOSEP 2024"
    },
    {
        "codigo": "LORTI",
        "titulo_contiene": "régimen tributario interno",
        "fecha_reforma": "2024-04-29",
        "ultimo_ro": "Suplemento RO 548, 29-IV-2024",
        "url_pdf": "",
        "descripcion": "Reforma tributaria 2024 — ajustes IVA y renta"
    },
    {
        "codigo": "COD-TRABAJO",
        "titulo_contiene": "código del trabajo",
        "fecha_reforma": "2023-07-26",
        "ultimo_ro": "Suplemento RO 355, 26-VII-2023",
        "url_pdf": "",
        "descripcion": "Reforma Código del Trabajo 2023"
    },
    {
        "codigo": "LOJ",
        "titulo_contiene": "código orgánico de la función judicial",
        "fecha_reforma": "2023-10-18",
        "ultimo_ro": "Suplemento RO 410, 18-X-2023",
        "url_pdf": "",
        "descripcion": "Reforma COFJ 2023"
    },
    {
        "codigo": "COMF",
        "titulo_contiene": "código orgánico monetario",
        "fecha_reforma": "2024-01-30",
        "ultimo_ro": "Suplemento RO 476, 30-I-2024",
        "url_pdf": "",
        "descripcion": "Reforma Código Orgánico Monetario y Financiero 2024"
    },
    {
        "codigo": "LCE",
        "titulo_contiene": "ley de compañías",
        "fecha_reforma": "2023-09-21",
        "ultimo_ro": "Suplemento RO 385, 21-IX-2023",
        "url_pdf": "",
        "descripcion": "Reforma Ley de Compañías 2023"
    },
    {
        "codigo": "COA",
        "titulo_contiene": "código orgánico del ambiente",
        "fecha_reforma": "2023-06-21",
        "ultimo_ro": "Suplemento RO 340, 21-VI-2023",
        "url_pdf": "",
        "descripcion": "Reforma COA 2023"
    },
    {
        "codigo": "LOEI",
        "titulo_contiene": "educación intercultural",
        "fecha_reforma": "2023-10-10",
        "ultimo_ro": "Suplemento RO 403, 10-X-2023",
        "url_pdf": "",
        "descripcion": "Reforma LOEI 2023"
    },
    {
        "codigo": "LOES",
        "titulo_contiene": "educación superior",
        "fecha_reforma": "2023-10-10",
        "ultimo_ro": "Suplemento RO 403, 10-X-2023",
        "url_pdf": "",
        "descripcion": "Reforma LOES 2023"
    },
    {
        "codigo": "LOGJCC",
        "titulo_contiene": "jurisdicción constitucional",
        "fecha_reforma": "2022-07-29",
        "ultimo_ro": "Suplemento RO 107, 29-VII-2022",
        "url_pdf": "",
        "descripcion": "Reforma Ley Orgánica de Garantías Jurisdiccionales 2022"
    },
]

# ── Fuentes para buscar PDFs actualizados ─────────────────────────────────────
FUENTES_PDF = [
    {"nombre": "Ministerio de Justicia", "base": "https://www.justicia.gob.ec/normativa/"},
    {"nombre": "Defensoría Pública",     "base": "https://biblioteca.defensoria.gob.ec/"},
    {"nombre": "Registro Oficial",       "base": "https://www.registroficial.gob.ec/"},
    {"nombre": "Presidencia",            "base": "https://www.presidencia.gob.ec/normativa/"},
]

# ── Supabase helpers ───────────────────────────────────────────────────────────
def sb_get(table, params=""):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}?{params}",
                     headers=HEADERS, timeout=30)
    if r.status_code == 200:
        return r.json()
    print(f"  ⚠ GET {table}: {r.status_code} {r.text[:100]}")
    return []

def sb_patch(table, id_, data):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{id_}",
        headers=HEADERS,
        data=json.dumps(data), timeout=30)
    return r.status_code in (200, 204)

def sb_insert(table, data):
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}",
                      headers=HEADERS, data=json.dumps(data), timeout=30)
    return r.status_code in (200, 201)

# ── Helpers ────────────────────────────────────────────────────────────────────
def normalizar(texto):
    import unicodedata
    t = texto.lower().strip()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", t)

def fecha_str_to_date(s):
    try:
        return date.fromisoformat(s[:10])
    except:
        return date(2000, 1, 1)

def verificar_pdf_activo(url):
    """Verifica si un PDF URL responde correctamente."""
    if not url or not url.startswith("http"):
        return False
    try:
        r = requests.head(url, timeout=10, allow_redirects=True)
        return r.status_code == 200
    except:
        return False

def buscar_pdf_en_registro_oficial(titulo_palabras):
    """Busca en el Registro Oficial por palabras clave del título."""
    try:
        query = "+".join(titulo_palabras[:3])
        url = f"https://www.registroficial.gob.ec/?s={query}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" in href.lower() and "registroficial" in href.lower():
                return href
    except:
        pass
    return None

# ── Verificación ───────────────────────────────────────────────────────────────
def verificar_norma(norma):
    """
    Verifica una norma y retorna dict con resultado.
    Estados: actualizada | desactualizada | posible_actualizacion | no_verificable
    """
    codigo   = (norma.get("codigo_unico") or "").upper()
    titulo   = normalizar(norma.get("titulo") or "")
    fecha_pub = fecha_str_to_date(norma.get("fecha_publicacion") or "2000-01-01")
    url_pdf   = (norma.get("url_pdf") or "").strip()
    hoy       = date.today()

    # Buscar en base de reformas
    reforma = None
    for ref in REFORMAS:
        if (ref["codigo"].upper() in codigo or
            ref["titulo_contiene"].lower() in titulo):
            reforma = ref
            break

    now_iso = datetime.now().isoformat()

    if not reforma:
        # Norma no está en la base de reformas conocidas
        # Verificar si el PDF sigue activo
        pdf_ok = verificar_pdf_activo(url_pdf) if url_pdf else False
        return {
            "estado_verificacion": "no_verificable",
            "fecha_verificacion":  now_iso,
            "detalles_verificacion": "No está en la base de reformas conocidas. " +
                ("PDF activo ✅" if pdf_ok else "Sin PDF o PDF inaccesible."),
            "pdf_activo": pdf_ok,
        }

    fecha_reforma = fecha_str_to_date(reforma["fecha_reforma"])
    dias_diferencia = (fecha_reforma - fecha_pub).days

    # Verificar PDF actual
    pdf_ok = verificar_pdf_activo(url_pdf) if url_pdf else False

    if fecha_pub >= fecha_reforma:
        return {
            "estado_verificacion": "actualizada",
            "fecha_verificacion":  now_iso,
            "detalles_verificacion": f"✅ Versión al día. Último RO conocido: {reforma['ultimo_ro']}",
            "pdf_activo": pdf_ok,
        }

    if dias_diferencia <= 90:
        return {
            "estado_verificacion": "posible_actualizacion",
            "fecha_verificacion":  now_iso,
            "detalles_verificacion": f"⚠️ Reforma reciente ({dias_diferencia} días): {reforma['descripcion']}. Nuevo RO: {reforma['ultimo_ro']}",
            "url_pdf_nuevo": reforma.get("url_pdf", ""),
            "pdf_activo": pdf_ok,
        }

    return {
        "estado_verificacion": "desactualizada",
        "fecha_verificacion":  now_iso,
        "detalles_verificacion": f"🔴 Reforma hace {dias_diferencia} días: {reforma['descripcion']}. Nuevo RO: {reforma['ultimo_ro']}",
        "url_pdf_nuevo": reforma.get("url_pdf", ""),
        "pdf_activo": pdf_ok,
    }

def actualizar_norma_en_supabase(norma_id, resultado):
    """Actualiza la norma en Supabase con el resultado de verificación."""
    update_data = {
        "verificado":   True,
        "estado":       "vigente" if resultado["estado_verificacion"] != "desactualizada" else "vigente",
        "resumen":      (resultado.get("detalles_verificacion") or "")[:600],
    }
    # Si encontramos URL de PDF actualizado, actualizarlo
    if resultado.get("url_pdf_nuevo"):
        update_data["url_pdf"] = resultado["url_pdf_nuevo"]

    return sb_patch("normas", norma_id, update_data)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("=" * 65)
    print("🔍 LexEC Robot Verificador y Actualizador")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    # Obtener todas las normas
    print("\n📥 Cargando normas desde Supabase...")
    normas = sb_get("normas",
        "select=id,codigo_unico,titulo,tipo,jerarquia,fecha_publicacion,"
        "url_pdf,resumen,estado,verificado,fuente"
        "&activo=eq.true&order=jerarquia.asc&limit=500")
    print(f"   Total normas activas: {len(normas)}")

    if not normas:
        print("❌ No se pudieron cargar normas")
        return

    # Estadísticas
    stats = {
        "actualizada": 0,
        "posible_actualizacion": 0,
        "desactualizada": 0,
        "no_verificable": 0,
        "pdf_actualizado": 0,
        "errores": 0,
    }

    print(f"\n🔎 Verificando {len(normas)} normas...\n")

    for i, norma in enumerate(normas):
        titulo_corto = (norma.get("titulo") or "")[:60]
        try:
            resultado = verificar_norma(norma)
            estado = resultado["estado_verificacion"]
            stats[estado] = stats.get(estado, 0) + 1

            # Solo actualizar en Supabase si está desactualizada o tiene PDF nuevo
            if estado in ("desactualizada", "posible_actualizacion"):
                if actualizar_norma_en_supabase(norma["id"], resultado):
                    if resultado.get("url_pdf_nuevo"):
                        stats["pdf_actualizado"] += 1
                        print(f"  🔄 [{estado}] {titulo_corto}")
                        print(f"     → PDF actualizado: {resultado['url_pdf_nuevo'][:60]}")
                    else:
                        print(f"  ⚠️  [{estado}] {titulo_corto}")
                        print(f"     → {resultado['detalles_verificacion'][:80]}")
            elif estado == "actualizada":
                # Marcar como verificada
                sb_patch("normas", norma["id"], {
                    "verificado": True,
                })
                if (i + 1) % 10 == 0:
                    print(f"  ✅ {i+1}/{len(normas)} verificadas...")

        except Exception as e:
            stats["errores"] += 1
            print(f"  ❌ Error en '{titulo_corto}': {e}")

        time.sleep(0.3)  # Rate limiting

    dur = round(time.time() - t0, 1)

    print("\n" + "=" * 65)
    print("📊 RESUMEN VERIFICACIÓN:")
    print(f"  ✅ Actualizadas:          {stats['actualizada']}")
    print(f"  ⚠️  Posible actualización: {stats['posible_actualizacion']}")
    print(f"  🔴 Desactualizadas:       {stats['desactualizada']}")
    print(f"  ❓ No verificables:       {stats['no_verificable']}")
    print(f"  🔄 PDFs actualizados:     {stats['pdf_actualizado']}")
    print(f"  ❌ Errores:               {stats['errores']}")
    print(f"\n⏱️  Tiempo total: {dur}s")
    print("=" * 65)

    # Log en Supabase
    total_issues = stats["posible_actualizacion"] + stats["desactualizada"]
    sb_insert("extracciones", {
        "fecha":    datetime.now().isoformat(),
        "fuente":   "Verificador GitHub Actions",
        "cantidad": stats["pdf_actualizado"],
        "estado":   "exitoso",
        "detalles": (f"Verificadas: {len(normas)} | "
                    f"Al día: {stats['actualizada']} | "
                    f"Con reformas: {total_issues} | "
                    f"PDFs actualizados: {stats['pdf_actualizado']}"),
    })

if __name__ == "__main__":
    main()
