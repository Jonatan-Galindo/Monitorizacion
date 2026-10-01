import base64
import os
import re
import sqlite3
from datetime import date
from io import StringIO

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    import plotly.graph_objects as go
except Exception:
    px = None
    go = None

DB = "database.db"
CARPETA_BASE = "datos_edificios"
LOGO_PATH = os.path.join("assets", "pgi_logo.png")
COLOR_CORPORATIVO = "#AB1735"
COLOR_CORPORATIVO_OSCURO = "#8C1E35"
COLOR_GRIS_FONDO = "#F6F7F8"
COLOR_GRIS_BORDE = "#E4E6EA"

st.set_page_config(page_title="Energía", layout="wide")


# ==================================================
# BASE DE DATOS / UTILIDADES
# ==================================================

def conectar_db():
    return sqlite3.connect(DB)


def inicializar_db():
    conn = conectar_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS edificios (
        codigo_proyecto TEXT PRIMARY KEY,
        nombre TEXT NOT NULL,
        cliente TEXT,
        ubicacion TEXT,
        uso TEXT,
        superficie_m2 REAL,
        sistema_climatizacion TEXT,
        estado TEXT DEFAULT 'ACTIVO',
        observaciones TEXT,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS simulaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_proyecto TEXT NOT NULL,
        nombre_simulacion TEXT NOT NULL,
        descripcion TEXT,
        activa INTEGER DEFAULT 0,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS simulacion_detalle (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        simulacion_id INTEGER NOT NULL,
        anio INTEGER NOT NULL,
        mes INTEGER NOT NULL,
        categoria TEXT NOT NULL,
        consumo_kwh REAL NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS consumos_bms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_proyecto TEXT NOT NULL,
        anio INTEGER NOT NULL,
        mes INTEGER NOT NULL,
        nombre_importacion TEXT NOT NULL,
        descripcion TEXT,
        fecha_importacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS consumo_bms_detalle (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consumo_bms_id INTEGER NOT NULL,
        categoria TEXT NOT NULL,
        consumo_kwh REAL NOT NULL,
        nombre_original_bms TEXT
    )
    """)

    for columna in ["electricidad_kwh", "gas_kwh"]:
        try:
            c.execute(f"ALTER TABLE consumo_bms_detalle ADD COLUMN {columna} REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass

    nuevas_columnas_edificios = {
        "categoria_edificio": "TEXT",
        "unidad_referencia": "TEXT DEFAULT 'm²'",
        "valor_unidad_referencia": "REAL DEFAULT 0",
        "habitaciones": "REAL DEFAULT 0",
        "puestos_trabajo": "REAL DEFAULT 0",
        "camas": "REAL DEFAULT 0",
        "horario_uso": "TEXT",
    }

    for columna, definicion in nuevas_columnas_edificios.items():
        try:
            c.execute(f"ALTER TABLE edificios ADD COLUMN {columna} {definicion}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def limpiar_nombre(texto):
    texto = str(texto).lower().strip()
    texto = re.sub(r"[^a-zA-Z0-9_-]", "_", texto)
    texto = re.sub(r"_+", "_", texto)
    return texto


def crear_carpetas_edificio(codigo, nombre):
    carpeta = os.path.join(CARPETA_BASE, f"{codigo}_{limpiar_nombre(nombre)}")
    os.makedirs(os.path.join(carpeta, "simulaciones"), exist_ok=True)
    os.makedirs(os.path.join(carpeta, "consumos_bms"), exist_ok=True)
    os.makedirs(os.path.join(carpeta, "informes"), exist_ok=True)
    return carpeta


def leer_texto_archivo(archivo):
    contenido = archivo.getvalue()
    for cod in ["utf-16", "utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            return contenido.decode(cod)
        except Exception:
            pass
    return contenido.decode("latin-1", errors="ignore")


def limpiar_numero(valor):
    if pd.isna(valor):
        return 0.0

    valor = str(valor).strip().replace(" ", "")

    if valor == "":
        return 0.0

    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")

    try:
        return float(valor)
    except Exception:
        return 0.0


def normalizar(texto):
    texto = str(texto).lower().strip()
    texto = texto.replace("\ufeff", "").replace("\xa0", " ")
    texto = texto.replace("á", "a").replace("é", "e").replace("í", "i")
    texto = texto.replace("ó", "o").replace("ú", "u")
    texto = re.sub(r"\s+", " ", texto)
    return texto


def leer_csv_flexible(archivo):
    texto = leer_texto_archivo(archivo)

    for sep in [",", ";", "\t"]:
        try:
            df = pd.read_csv(StringIO(texto), sep=sep, engine="python")
            if len(df.columns) > 1:
                return df
        except Exception:
            pass

    return pd.read_csv(StringIO(texto), sep=None, engine="python")


# ==================================================
# EDIFICIOS
# ==================================================

def cargar_edificios(incluir_archivados=False):
    conn = conectar_db()
    query = "SELECT * FROM edificios ORDER BY nombre"

    if not incluir_archivados:
        query = "SELECT * FROM edificios WHERE estado='ACTIVO' ORDER BY nombre"

    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def guardar_edificio(datos):
    conn = conectar_db()
    c = conn.cursor()

    c.execute("""
        INSERT INTO edificios (
            codigo_proyecto, nombre, cliente, ubicacion, uso,
            superficie_m2, categoria_edificio, unidad_referencia,
            valor_unidad_referencia, habitaciones, puestos_trabajo, camas,
            horario_uso, sistema_climatizacion, estado, observaciones
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVO', ?)
    """, (
        datos["codigo_proyecto"],
        datos["nombre"],
        datos["cliente"],
        datos["ubicacion"],
        datos["uso"],
        datos["superficie_m2"],
        datos.get("categoria_edificio", datos.get("uso", "")),
        datos.get("unidad_referencia", "m²"),
        datos.get("valor_unidad_referencia", 0),
        datos.get("habitaciones", 0),
        datos.get("puestos_trabajo", 0),
        datos.get("camas", 0),
        datos.get("horario_uso", ""),
        datos["sistema_climatizacion"],
        datos["observaciones"],
    ))

    conn.commit()
    conn.close()


def actualizar_edificio(codigo, datos):
    conn = conectar_db()
    c = conn.cursor()

    c.execute("""
        UPDATE edificios
        SET nombre=?, cliente=?, ubicacion=?, uso=?, superficie_m2=?,
            categoria_edificio=?, unidad_referencia=?, valor_unidad_referencia=?,
            habitaciones=?, puestos_trabajo=?, camas=?, horario_uso=?,
            sistema_climatizacion=?, observaciones=?
        WHERE codigo_proyecto=?
    """, (
        datos["nombre"],
        datos["cliente"],
        datos["ubicacion"],
        datos["uso"],
        datos["superficie_m2"],
        datos.get("categoria_edificio", datos.get("uso", "")),
        datos.get("unidad_referencia", "m²"),
        datos.get("valor_unidad_referencia", 0),
        datos.get("habitaciones", 0),
        datos.get("puestos_trabajo", 0),
        datos.get("camas", 0),
        datos.get("horario_uso", ""),
        datos["sistema_climatizacion"],
        datos["observaciones"],
        codigo,
    ))

    conn.commit()
    conn.close()


def cambiar_estado_edificio(codigo, estado):
    conn = conectar_db()
    c = conn.cursor()
    c.execute("UPDATE edificios SET estado=? WHERE codigo_proyecto=?", (estado, codigo))
    conn.commit()
    conn.close()


def resumen_datos_edificio(codigo):
    conn = conectar_db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM simulaciones WHERE codigo_proyecto=?", (codigo,))
    simulaciones = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*)
        FROM simulacion_detalle
        WHERE simulacion_id IN (
            SELECT id FROM simulaciones WHERE codigo_proyecto=?
        )
    """, (codigo,))
    detalle_simulaciones = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM consumos_bms WHERE codigo_proyecto=?", (codigo,))
    consumos_bms = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*)
        FROM consumo_bms_detalle
        WHERE consumo_bms_id IN (
            SELECT id FROM consumos_bms WHERE codigo_proyecto=?
        )
    """, (codigo,))
    detalle_bms = c.fetchone()[0]

    conn.close()

    return {
        "simulaciones": simulaciones,
        "detalle_simulaciones": detalle_simulaciones,
        "consumos_bms": consumos_bms,
        "detalle_bms": detalle_bms,
    }


def eliminar_edificio(codigo):
    conn = conectar_db()
    c = conn.cursor()

    try:
        c.execute("""
            DELETE FROM simulacion_detalle
            WHERE simulacion_id IN (
                SELECT id FROM simulaciones WHERE codigo_proyecto=?
            )
        """, (codigo,))
        detalle_simulaciones = c.rowcount

        c.execute("""
            DELETE FROM consumo_bms_detalle
            WHERE consumo_bms_id IN (
                SELECT id FROM consumos_bms WHERE codigo_proyecto=?
            )
        """, (codigo,))
        detalle_bms = c.rowcount

        c.execute("DELETE FROM simulaciones WHERE codigo_proyecto=?", (codigo,))
        simulaciones = c.rowcount

        c.execute("DELETE FROM consumos_bms WHERE codigo_proyecto=?", (codigo,))
        consumos_bms = c.rowcount

        c.execute("DELETE FROM edificios WHERE codigo_proyecto=?", (codigo,))
        edificios = c.rowcount

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "edificios": edificios,
        "simulaciones": simulaciones,
        "detalle_simulaciones": detalle_simulaciones,
        "consumos_bms": consumos_bms,
        "detalle_bms": detalle_bms,
    }


# ==================================================
# SIMULACIONES
# ==================================================

MAPEO_DAT = {
    "Lighting": "Interior Lighting",
    "Interior Lighting": "Interior Lighting",
    "Exterior lighting": "Exterior Lighting",
    "Exterior Lighting": "Exterior Lighting",
    "System Fans": "Fans",
    "Fans": "Fans",
    "System Pumps": "Pumps",
    "Pumps": "Pumps",
    "Heating (Electricity)": "Heating",
    "Heating": "Heating",
    "Cooling (Electricity)": "Cooling",
    "Cooling": "Cooling",
    "Interior Equipment": "Interior Equipment",
    "Exterior Equipment": "Exterior Equipment",
    "Water Systems": "Water Systems",
    "Refrigeration": "Refrigeration",
    "Generators": "Generators",
    "Heat Rejection": "Heat Rejection",
    "Humidification": "Humidification",
    "Heat Recovery": "Heat Recovery",
}


def transformar_dat_designbuilder(archivo, anio):
    texto = leer_texto_archivo(archivo)

    try:
        df = pd.read_csv(
            StringIO(texto),
            sep="\t",
            decimal=",",
            header=0,
            engine="python"
        )
    except Exception as e:
        return None, [], [f"No se pudo leer el .dat: {e}"]

    if df.empty:
        return None, [], ["El archivo .dat está vacío."]

    primera_columna = df.columns[0]
    datos = []
    ignoradas = []

    for _, fila in df.iterrows():
        categoria_original = str(fila[primera_columna]).strip()

        if categoria_original == "" or categoria_original.lower() == "nan":
            continue

        if categoria_original not in MAPEO_DAT:
            ignoradas.append(categoria_original)
            continue

        categoria = MAPEO_DAT[categoria_original]

        for mes in range(1, 13):
            valor = fila.iloc[mes] if mes < len(fila) else 0

            datos.append({
                "anio": int(anio),
                "mes": mes,
                "categoria": categoria,
                "consumo_kwh": limpiar_numero(valor),
            })

    df_final = pd.DataFrame(datos)

    if df_final.empty:
        return None, sorted(set(ignoradas)), ["No se encontraron categorías reconocidas."]

    return df_final, sorted(set(ignoradas)), []


def crear_simulacion(codigo, nombre, descripcion, activa):
    conn = conectar_db()
    c = conn.cursor()

    if activa:
        c.execute("UPDATE simulaciones SET activa=0 WHERE codigo_proyecto=?", (codigo,))

    c.execute("""
        INSERT INTO simulaciones (codigo_proyecto, nombre_simulacion, descripcion, activa)
        VALUES (?, ?, ?, ?)
    """, (codigo, nombre, descripcion, 1 if activa else 0))

    sim_id = c.lastrowid
    conn.commit()
    conn.close()
    return sim_id


def guardar_detalle_simulacion(sim_id, df):
    conn = conectar_db()
    c = conn.cursor()

    for _, fila in df.iterrows():
        c.execute("""
            INSERT INTO simulacion_detalle (simulacion_id, anio, mes, categoria, consumo_kwh)
            VALUES (?, ?, ?, ?, ?)
        """, (
            int(sim_id),
            int(fila["anio"]),
            int(fila["mes"]),
            fila["categoria"],
            float(fila["consumo_kwh"]),
        ))

    conn.commit()
    conn.close()


def cargar_simulaciones(codigo):
    conn = conectar_db()
    df = pd.read_sql_query(
        "SELECT * FROM simulaciones WHERE codigo_proyecto=? ORDER BY fecha_creacion DESC",
        conn,
        params=(codigo,)
    )
    conn.close()
    return df


def cargar_simulacion_activa(codigo):
    conn = conectar_db()
    df = pd.read_sql_query(
        "SELECT * FROM simulaciones WHERE codigo_proyecto=? AND activa=1 LIMIT 1",
        conn,
        params=(codigo,)
    )
    conn.close()
    return df


def cargar_detalle_simulacion(sim_id):
    conn = conectar_db()
    df = pd.read_sql_query(
        "SELECT * FROM simulacion_detalle WHERE simulacion_id=? ORDER BY anio, mes, categoria",
        conn,
        params=(int(sim_id),)
    )
    conn.close()
    return df


def marcar_simulacion_activa(sim_id, codigo):
    conn = conectar_db()
    c = conn.cursor()
    c.execute("UPDATE simulaciones SET activa=0 WHERE codigo_proyecto=?", (codigo,))
    c.execute("UPDATE simulaciones SET activa=1 WHERE id=?", (int(sim_id),))
    conn.commit()
    conn.close()


# ==================================================
# BMS
# ==================================================

def transformar_csv_bms(archivo):
    df = leer_csv_flexible(archivo)

    df.columns = [
        str(c).replace("\ufeff", "").replace("\xa0", " ").strip()
        for c in df.columns
    ]

    columnas = {normalizar(c): c for c in df.columns}

    col_tipologia = None
    col_elec = None
    col_gas = None

    for k, v in columnas.items():
        if k in ["tipologia", "tipología", "categoria", "category"]:
            col_tipologia = v
        if k in ["electricidad [kwh]", "electricidad", "electricity [kwh]", "electricity"]:
            col_elec = v
        if k in ["gas natural [kwh]", "gas natural", "gas [kwh]", "gas"]:
            col_gas = v

    errores = []

    if col_tipologia is None:
        errores.append(f"No encuentro columna Tipologia. Detectadas: {list(df.columns)}")
    if col_elec is None:
        errores.append(f"No encuentro columna Electricidad [kWh]. Detectadas: {list(df.columns)}")
    if col_gas is None:
        errores.append(f"No encuentro columna Gas Natural [kWh]. Detectadas: {list(df.columns)}")

    if errores:
        return None, errores

    datos = []

    for _, fila in df.iterrows():
        categoria = str(fila[col_tipologia]).strip()

        if categoria == "" or categoria.lower() == "nan":
            continue

        if normalizar(categoria) in ["total mes", "total", "totales"]:
            continue

        electricidad = limpiar_numero(fila[col_elec])
        gas = limpiar_numero(fila[col_gas])

        datos.append({
            "categoria": categoria,
            "electricidad_kwh": electricidad,
            "gas_kwh": gas,
            "consumo_kwh": electricidad + gas,
            "nombre_original_bms": categoria,
        })

    resultado = pd.DataFrame(datos)

    if resultado.empty:
        return None, ["No se encontraron consumos válidos en el CSV BMS."]

    return resultado, []


def crear_consumo_bms(codigo, anio, mes, nombre, descripcion):
    conn = conectar_db()
    c = conn.cursor()

    c.execute("""
        INSERT INTO consumos_bms (codigo_proyecto, anio, mes, nombre_importacion, descripcion)
        VALUES (?, ?, ?, ?, ?)
    """, (codigo, int(anio), int(mes), nombre, descripcion))

    bms_id = c.lastrowid
    conn.commit()
    conn.close()
    return bms_id


def guardar_detalle_bms(bms_id, df):
    conn = conectar_db()
    c = conn.cursor()

    for _, fila in df.iterrows():
        c.execute("""
            INSERT INTO consumo_bms_detalle (
                consumo_bms_id, categoria, consumo_kwh, nombre_original_bms,
                electricidad_kwh, gas_kwh
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            int(bms_id),
            fila["categoria"],
            float(fila["consumo_kwh"]),
            fila["nombre_original_bms"],
            float(fila.get("electricidad_kwh", 0)),
            float(fila.get("gas_kwh", 0)),
        ))

    conn.commit()
    conn.close()


def cargar_consumos_bms(codigo):
    conn = conectar_db()
    df = pd.read_sql_query(
        "SELECT * FROM consumos_bms WHERE codigo_proyecto=? ORDER BY anio DESC, mes DESC, id DESC",
        conn,
        params=(codigo,)
    )
    conn.close()
    return df


def cargar_detalle_bms(bms_id):
    conn = conectar_db()
    df = pd.read_sql_query("""
        SELECT 
            categoria,
            consumo_kwh,
            COALESCE(electricidad_kwh, 0) AS electricidad_kwh,
            COALESCE(gas_kwh, 0) AS gas_kwh,
            nombre_original_bms
        FROM consumo_bms_detalle
        WHERE consumo_bms_id=?
        ORDER BY categoria
    """, conn, params=(int(bms_id),))
    conn.close()
    return df


def cargar_ultimo_bms_mes(codigo, anio, mes):
    conn = conectar_db()

    df = pd.read_sql_query("""
        SELECT 
            cbd.categoria,
            cbd.consumo_kwh AS real_kwh,
            COALESCE(cbd.electricidad_kwh, 0) AS electricidad_kwh,
            COALESCE(cbd.gas_kwh, 0) AS gas_kwh
        FROM consumo_bms_detalle cbd
        JOIN consumos_bms cb ON cb.id = cbd.consumo_bms_id
        WHERE cb.codigo_proyecto = ?
        AND cb.anio = ?
        AND cb.mes = ?
        AND cb.id = (
            SELECT MAX(id)
            FROM consumos_bms
            WHERE codigo_proyecto = ?
            AND anio = ?
            AND mes = ?
        )
    """, conn, params=(codigo, int(anio), int(mes), codigo, int(anio), int(mes)))

    conn.close()
    return df


def meses_bms(codigo, anio):
    conn = conectar_db()
    df = pd.read_sql_query("""
        SELECT mes, MAX(id) AS bms_id
        FROM consumos_bms
        WHERE codigo_proyecto = ?
        AND anio = ?
        GROUP BY mes
        ORDER BY mes
    """, conn, params=(codigo, int(anio)))
    conn.close()
    return df


# ==================================================
# COMPARATIVAS
# ==================================================

def comparativa_mensual(codigo, sim_id, anio, mes):
    conn = conectar_db()

    sim = pd.read_sql_query("""
        SELECT categoria, consumo_kwh AS simulado_kwh
        FROM simulacion_detalle
        WHERE simulacion_id = ?
        AND anio = ?
        AND mes = ?
    """, conn, params=(int(sim_id), int(anio), int(mes)))

    conn.close()

    bms = cargar_ultimo_bms_mes(codigo, anio, mes)

    if bms.empty:
        return pd.DataFrame()

    bms_simple = bms[["categoria", "real_kwh"]].copy()

    comp = pd.merge(sim, bms_simple, on="categoria", how="outer").fillna(0)
    comp["desviacion_kwh"] = comp["real_kwh"] - comp["simulado_kwh"]
    comp["desviacion_pct"] = comp.apply(
        lambda r: 0 if r["simulado_kwh"] == 0 else round(r["desviacion_kwh"] / r["simulado_kwh"] * 100, 2),
        axis=1
    )
    comp["estado"] = comp["desviacion_pct"].apply(clasificar_alerta)

    return comp.sort_values("desviacion_kwh", ascending=False)


def comparativa_parcial_anual(codigo, sim_id, anio):
    meses = meses_bms(codigo, anio)

    if meses.empty:
        return pd.DataFrame(), pd.DataFrame()

    conn = conectar_db()
    datos_meses = []

    for _, row in meses.iterrows():
        mes = int(row["mes"])
        bms_id = int(row["bms_id"])

        sim = pd.read_sql_query("""
            SELECT SUM(consumo_kwh) AS total
            FROM simulacion_detalle
            WHERE simulacion_id = ?
            AND anio = ?
            AND mes = ?
        """, conn, params=(int(sim_id), int(anio), mes))

        total_sim = sim.iloc[0]["total"]
        total_sim = 0 if pd.isna(total_sim) else total_sim

        bms = pd.read_sql_query("""
            SELECT SUM(consumo_kwh) AS total
            FROM consumo_bms_detalle
            WHERE consumo_bms_id = ?
        """, conn, params=(bms_id,))

        total_real = bms.iloc[0]["total"]
        total_real = 0 if pd.isna(total_real) else total_real

        desviacion = total_real - total_sim
        desviacion_pct = 0 if total_sim == 0 else round(desviacion / total_sim * 100, 2)

        datos_meses.append({
            "mes": mes,
            "simulado_kwh": round(total_sim, 2),
            "real_kwh": round(total_real, 2),
            "desviacion_kwh": round(desviacion, 2),
            "desviacion_pct": desviacion_pct
        })

    df_meses = pd.DataFrame(datos_meses)

    meses_texto = ",".join(str(int(m)) for m in meses["mes"].tolist())
    ids_texto = ",".join(str(int(i)) for i in meses["bms_id"].tolist())

    sim_cat = pd.read_sql_query(f"""
        SELECT categoria, SUM(consumo_kwh) AS simulado_kwh
        FROM simulacion_detalle
        WHERE simulacion_id = ?
        AND anio = ?
        AND mes IN ({meses_texto})
        GROUP BY categoria
    """, conn, params=(int(sim_id), int(anio)))

    bms_cat = pd.read_sql_query(f"""
        SELECT categoria, SUM(consumo_kwh) AS real_kwh
        FROM consumo_bms_detalle
        WHERE consumo_bms_id IN ({ids_texto})
        GROUP BY categoria
    """, conn)

    conn.close()

    comp_cat = pd.merge(sim_cat, bms_cat, on="categoria", how="outer").fillna(0)
    comp_cat["desviacion_kwh"] = comp_cat["real_kwh"] - comp_cat["simulado_kwh"]
    comp_cat["desviacion_pct"] = comp_cat.apply(
        lambda r: 0 if r["simulado_kwh"] == 0 else round(r["desviacion_kwh"] / r["simulado_kwh"] * 100, 2),
        axis=1
    )

    return df_meses, comp_cat.sort_values("desviacion_kwh", ascending=False)


def clasificar_alerta(desviacion_pct):
    valor = abs(desviacion_pct)
    if valor <= 10:
        return "🟢 Correcto"
    elif valor <= 20:
        return "🟡 Atención"
    else:
        return "🔴 Revisar"


def generar_observaciones(comp):
    observaciones = []

    altas = comp[comp["desviacion_pct"] > 15]
    bajas = comp[comp["desviacion_pct"] < -15]

    for _, fila in altas.iterrows():
        observaciones.append(
            f"- {fila['categoria']}: consumo real superior al simulado en {fila['desviacion_pct']}%. "
            "Revisar horarios, consignas, ocupación o funcionamiento del BMS."
        )

    for _, fila in bajas.iterrows():
        observaciones.append(
            f"- {fila['categoria']}: consumo real inferior al simulado en "
            f"{abs(fila['desviacion_pct'])}%. Revisar menor uso, ocupación o condiciones favorables."
        )

    if not observaciones:
        observaciones.append("- No se detectan desviaciones significativas superiores al 15%.")

    return "\n".join(observaciones)


# ==================================================
# COSTES / CO2
# ==================================================

def consumos_bms_anio(codigo, anio):
    meses = meses_bms(codigo, anio)

    if meses.empty:
        return pd.DataFrame()

    ids = ",".join(str(int(x)) for x in meses["bms_id"].tolist())

    conn = conectar_db()
    df = pd.read_sql_query(f"""
        SELECT 
            cb.mes,
            cbd.categoria,
            cbd.consumo_kwh,
            COALESCE(cbd.electricidad_kwh, 0) AS electricidad_kwh,
            COALESCE(cbd.gas_kwh, 0) AS gas_kwh
        FROM consumo_bms_detalle cbd
        JOIN consumos_bms cb ON cb.id = cbd.consumo_bms_id
        WHERE cbd.consumo_bms_id IN ({ids})
        ORDER BY cb.mes, cbd.categoria
    """, conn)
    conn.close()

    if (
        df["electricidad_kwh"].sum() == 0
        and df["gas_kwh"].sum() == 0
        and df["consumo_kwh"].sum() > 0
    ):
        df["electricidad_kwh"] = df["consumo_kwh"]
        df["gas_kwh"] = 0

    return df


# ==================================================
# UI / COMPONENTES
# ==================================================

ANIO_ACTUAL = date.today().year

MESES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}

TIPOS_EDIFICIO = [
    "Oficinas",
    "Hotel",
    "Residencial",
    "Hospitalario",
    "Docente",
    "Comercial",
    "Industrial",
    "Otro",
]

UNIDADES_REFERENCIA = ["m²", "habitaciones", "puestos de trabajo", "camas", "usuarios", "otro"]


def obtener_valor_referencia(edificio):
    unidad = edificio.get("unidad_referencia", "m²") if hasattr(edificio, "get") else "m²"
    valor = edificio.get("valor_unidad_referencia", 0) if hasattr(edificio, "get") else 0

    if pd.isna(valor) or float(valor) <= 0:
        if unidad == "habitaciones":
            valor = edificio.get("habitaciones", 0) if hasattr(edificio, "get") else 0
        elif unidad == "puestos de trabajo":
            valor = edificio.get("puestos_trabajo", 0) if hasattr(edificio, "get") else 0
        elif unidad == "camas":
            valor = edificio.get("camas", 0) if hasattr(edificio, "get") else 0
        else:
            valor = edificio.get("superficie_m2", 0) if hasattr(edificio, "get") else 0

    try:
        valor = float(valor)
    except Exception:
        valor = 0

    if valor <= 0:
        superficie = edificio.get("superficie_m2", 0) if hasattr(edificio, "get") else 0
        try:
            valor = float(superficie)
            unidad = "m²"
        except Exception:
            valor = 0

    return unidad or "m²", valor


def indicador_especifico(consumo_kwh, edificio):
    unidad, valor = obtener_valor_referencia(edificio)
    if valor <= 0:
        return "Sin dato", 0, unidad
    return f"kWh/{unidad}", consumo_kwh / valor, unidad


def plotly_disponible():
    if px is None or go is None:
        st.info("Para activar los gráficos avanzados instala Plotly: pip install plotly")
        return False
    return True


def grafico_barras_comparativa(df, titulo):
    if not plotly_disponible() or df.empty:
        return
    datos = df.copy().sort_values("real_kwh", ascending=True)
    fig = go.Figure()
    fig.add_bar(
        y=datos["categoria"],
        x=datos["simulado_kwh"],
        name="Simulado",
        orientation="h",
        marker_color="#A7B0BE",
    )
    fig.add_bar(
        y=datos["categoria"],
        x=datos["real_kwh"],
        name="Real BMS",
        orientation="h",
        marker_color=COLOR_CORPORATIVO,
    )
    fig.update_layout(
        title=titulo,
        barmode="group",
        height=max(420, 32 * len(datos)),
        xaxis_title="kWh",
        yaxis_title="",
        legend_title="",
        margin=dict(l=10, r=10, t=55, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def grafico_desviacion(df, titulo):
    if not plotly_disponible() or df.empty:
        return
    datos = df.copy().sort_values("desviacion_kwh")
    datos["tipo_desviacion"] = datos["desviacion_kwh"].apply(lambda x: "Mayor consumo" if x >= 0 else "Menor consumo")
    fig = px.bar(
        datos,
        y="categoria",
        x="desviacion_kwh",
        color="tipo_desviacion",
        orientation="h",
        text="desviacion_pct",
        title=titulo,
        labels={"desviacion_kwh": "Desviación kWh", "categoria": "", "tipo_desviacion": ""},
        color_discrete_map={"Mayor consumo": COLOR_CORPORATIVO, "Menor consumo": "#4B5563"},
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside", cliponaxis=False)
    fig.update_layout(height=max(420, 32 * len(datos)), margin=dict(l=10, r=40, t=55, b=10))
    st.plotly_chart(fig, use_container_width=True)


def grafico_pareto_desviaciones(df, titulo):
    if not plotly_disponible() or df.empty:
        return
    datos = df.copy()
    datos["impacto_abs"] = datos["desviacion_kwh"].abs()
    datos = datos.sort_values("impacto_abs", ascending=False)
    total = datos["impacto_abs"].sum()
    datos["impacto_acumulado_pct"] = 0 if total == 0 else datos["impacto_abs"].cumsum() / total * 100

    fig = go.Figure()
    fig.add_bar(
        x=datos["categoria"],
        y=datos["impacto_abs"],
        name="Impacto absoluto",
        marker_color=COLOR_CORPORATIVO,
    )
    fig.add_scatter(
        x=datos["categoria"],
        y=datos["impacto_acumulado_pct"],
        name="Acumulado",
        yaxis="y2",
        mode="lines+markers",
        line=dict(color="#23272F", width=3),
    )
    fig.update_layout(
        title=titulo,
        yaxis=dict(title="kWh de desviación absoluta"),
        yaxis2=dict(title="Impacto acumulado %", overlaying="y", side="right", range=[0, 105]),
        xaxis=dict(title="", tickangle=-30),
        legend_title="",
        height=460,
        margin=dict(l=10, r=10, t=55, b=80),
    )
    st.plotly_chart(fig, use_container_width=True)


def grafico_evolucion_mensual(df_meses, titulo):
    if not plotly_disponible() or df_meses.empty:
        return
    datos = df_meses.copy()
    datos["mes_nombre"] = datos["mes"].map(lambda m: MESES.get(int(m), str(m)))
    fig = go.Figure()
    fig.add_scatter(x=datos["mes_nombre"], y=datos["simulado_kwh"], name="Simulado", mode="lines+markers", line=dict(width=3, color="#A7B0BE"))
    fig.add_scatter(x=datos["mes_nombre"], y=datos["real_kwh"], name="Real BMS", mode="lines+markers", line=dict(width=3, color=COLOR_CORPORATIVO))
    fig.add_bar(x=datos["mes_nombre"], y=datos["desviacion_kwh"], name="Desviación", marker_color="#4B5563", opacity=0.35)
    fig.update_layout(
        title=titulo,
        yaxis_title="kWh",
        xaxis_title="",
        legend_title="",
        height=460,
        margin=dict(l=10, r=10, t=55, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def grafico_ranking_indicadores(df, titulo):
    if not plotly_disponible() or df.empty:
        return
    fig = px.bar(
        df.sort_values("indicador_especifico", ascending=True),
        x="indicador_especifico",
        y="nombre",
        color="categoria_edificio",
        orientation="h",
        title=titulo,
        labels={"indicador_especifico": "Indicador específico", "nombre": "", "categoria_edificio": "Categoría"},
    )
    fig.update_layout(height=max(420, 32 * len(df)), margin=dict(l=10, r=10, t=55, b=10))
    st.plotly_chart(fig, use_container_width=True)


COLUMN_CONFIG = {
    "codigo_proyecto": st.column_config.TextColumn("Código"),
    "nombre": st.column_config.TextColumn("Nombre"),
    "cliente": st.column_config.TextColumn("Cliente"),
    "ubicacion": st.column_config.TextColumn("Ubicación"),
    "uso": st.column_config.TextColumn("Uso"),
    "categoria_edificio": st.column_config.TextColumn("Categoría edificio"),
    "unidad_referencia": st.column_config.TextColumn("Unidad referencia"),
    "valor_unidad_referencia": st.column_config.NumberColumn("Valor referencia", format="%.0f"),
    "habitaciones": st.column_config.NumberColumn("Habitaciones", format="%.0f"),
    "puestos_trabajo": st.column_config.NumberColumn("Puestos", format="%.0f"),
    "camas": st.column_config.NumberColumn("Camas", format="%.0f"),
    "horario_uso": st.column_config.TextColumn("Horario de uso"),
    "estado": st.column_config.TextColumn("Estado"),
    "superficie_m2": st.column_config.NumberColumn("Superficie", format="%.0f m²"),
    "anio": st.column_config.NumberColumn("Año", format="%d"),
    "mes": st.column_config.NumberColumn("Mes", format="%d"),
    "categoria": st.column_config.TextColumn("Categoría"),
    "consumo_kwh": st.column_config.NumberColumn("Consumo", format="%.0f kWh"),
    "simulado_kwh": st.column_config.NumberColumn("Simulado", format="%.0f kWh"),
    "real_kwh": st.column_config.NumberColumn("Real BMS", format="%.0f kWh"),
    "desviacion_kwh": st.column_config.NumberColumn("Desviación", format="%.0f kWh"),
    "desviacion_pct": st.column_config.NumberColumn("Desviación", format="%.2f %%"),
    "electricidad_kwh": st.column_config.NumberColumn("Electricidad", format="%.0f kWh"),
    "gas_kwh": st.column_config.NumberColumn("Gas", format="%.0f kWh"),
    "coste_electricidad_eur": st.column_config.NumberColumn("Electricidad", format="%.2f €"),
    "coste_gas_eur": st.column_config.NumberColumn("Gas", format="%.2f €"),
    "coste_total_eur": st.column_config.NumberColumn("Coste total", format="%.2f €"),
    "co2_electricidad_kg": st.column_config.NumberColumn("Electricidad", format="%.0f kgCO₂"),
    "co2_gas_kg": st.column_config.NumberColumn("Gas", format="%.0f kgCO₂"),
    "co2_total_kg": st.column_config.NumberColumn("CO₂ total", format="%.0f kgCO₂"),
    "indicador_especifico": st.column_config.NumberColumn("Indicador específico", format="%.2f"),
    "unidad_indicador": st.column_config.TextColumn("Unidad indicador"),
}


def aplicar_estilos():
    css = """
    <style>
        :root {
            --pgi-primary: __PGI_PRIMARY__;
            --pgi-primary-dark: __PGI_PRIMARY_DARK__;
            --pgi-bg: __PGI_BG__;
            --pgi-border: __PGI_BORDER__;
            --pgi-text: #23272f;
            --pgi-muted: #667085;
        }

        .stApp {
            background: linear-gradient(180deg, #ffffff 0%, var(--pgi-bg) 100%);
            color: var(--pgi-text);
        }

        .block-container {
            padding-top: 1rem;
            padding-bottom: 2.5rem;
        }

        [data-testid="stSidebar"] {
            background: #f8f9fa;
            border-right: 1px solid var(--pgi-border);
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--pgi-primary-dark);
        }

        .pgi-header {
            display: flex;
            align-items: center;
            gap: 1.4rem;
            border-bottom: 1px solid var(--pgi-border);
            padding: 0.35rem 0 1.1rem 0;
            margin-bottom: 1rem;
        }

        .pgi-header img {
            width: 310px;
            max-width: 42vw;
            height: auto;
        }

        .pgi-header h1 {
            color: var(--pgi-primary-dark);
            font-size: 2.05rem;
            line-height: 1.1;
            margin: 0 0 0.25rem 0;
            font-weight: 750;
        }

        .pgi-header p {
            color: var(--pgi-muted);
            margin: 0;
            font-size: 0.98rem;
        }

        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--pgi-border);
            border-left: 4px solid var(--pgi-primary);
            border-radius: 8px;
            padding: 0.8rem 0.9rem;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }

        [data-testid="stMetricLabel"] {
            color: var(--pgi-muted);
        }

        [data-testid="stMetricValue"] {
            font-size: 1.35rem;
            color: var(--pgi-text);
        }

        div[data-testid="stTabs"] button {
            font-weight: 600;
        }

        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--pgi-primary);
            border-bottom-color: var(--pgi-primary);
        }

        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stFormSubmitButton"] button {
            background: var(--pgi-primary);
            border: 1px solid var(--pgi-primary);
            color: #ffffff;
            border-radius: 7px;
            font-weight: 650;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        [data-testid="stFormSubmitButton"] button:hover {
            background: var(--pgi-primary-dark);
            border-color: var(--pgi-primary-dark);
            color: #ffffff;
        }

        .stTextInput input:focus,
        .stNumberInput input:focus,
        .stTextArea textarea:focus,
        [data-baseweb="select"] > div:focus-within {
            border-color: var(--pgi-primary);
            box-shadow: 0 0 0 1px var(--pgi-primary);
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--pgi-border);
            border-radius: 8px;
            overflow: hidden;
        }

        @media (max-width: 760px) {
            .pgi-header {
                display: block;
            }

            .pgi-header img {
                max-width: 92vw;
                margin-bottom: 0.8rem;
            }
        }
    </style>
    """

    css = (
        css
        .replace("__PGI_PRIMARY__", COLOR_CORPORATIVO)
        .replace("__PGI_PRIMARY_DARK__", COLOR_CORPORATIVO_OSCURO)
        .replace("__PGI_BG__", COLOR_GRIS_FONDO)
        .replace("__PGI_BORDER__", COLOR_GRIS_BORDE)
    )

    st.markdown(css, unsafe_allow_html=True)


def mostrar_cabecera_app():
    if os.path.exists(LOGO_PATH):
        st.logo(LOGO_PATH, size="large")
        with open(LOGO_PATH, "rb") as logo_file:
            logo_base64 = base64.b64encode(logo_file.read()).decode("utf-8")

        st.markdown(
            f"""
            <div class="pgi-header">
                <img src="data:image/png;base64,{logo_base64}" alt="Logo">
                <div>
                    <h1>Energía</h1>
                    <p>Seguimiento operativo de simulaciones, consumos BMS, desviaciones, costes y emisiones.</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.title("Energía")
        st.caption("Seguimiento operativo de simulaciones, consumos BMS, desviaciones, costes y emisiones.")


def etiqueta_mes(mes):
    return f"{int(mes):02d} - {MESES[int(mes)]}"


def opciones_edificios(df):
    return [
        f"{row['codigo_proyecto']} - {row['nombre']}"
        for _, row in df.iterrows()
    ]


def codigo_desde_opcion(opcion):
    return opcion.split(" - ")[0]


def seleccionar_fila_edificio(df, codigo):
    return df[df["codigo_proyecto"] == codigo].iloc[0]


def mostrar_dataframe(df, height=None):
    config = {
        columna: COLUMN_CONFIG[columna]
        for columna in df.columns
        if columna in COLUMN_CONFIG
    }

    opciones = {
        "width": "stretch",
        "hide_index": True,
        "column_config": config,
    }

    if height is not None:
        opciones["height"] = height

    st.dataframe(df, **opciones)


def mostrar_mensaje_estado():
    mensaje = st.session_state.pop("mensaje_estado", None)
    if mensaje:
        st.success(mensaje)


def guardar_mensaje_y_recargar(mensaje):
    st.session_state["mensaje_estado"] = mensaje
    st.rerun()


def mostrar_contexto(codigo, edificio, anio, mes=None):
    periodo = str(anio)
    if mes is not None:
        periodo = f"{MESES[int(mes)]} {anio}"

    st.caption(
        f"Contexto activo: {codigo} · {edificio['nombre']} · {periodo}"
    )


def configurar_sidebar(edificios_activos):
    st.sidebar.header("Contexto")

    if edificios_activos.empty:
        st.sidebar.warning("Crea un edificio activo para empezar.")
        return None, None, ANIO_ACTUAL, 1

    opciones = opciones_edificios(edificios_activos)
    opcion = st.sidebar.selectbox("Edificio activo", opciones, key="global_edificio")
    codigo = codigo_desde_opcion(opcion)
    edificio = seleccionar_fila_edificio(edificios_activos, codigo)

    anio = st.sidebar.number_input(
        "Año de análisis",
        2000,
        2100,
        ANIO_ACTUAL,
        key="global_anio"
    )
    mes = st.sidebar.selectbox(
        "Mes de análisis",
        list(MESES.keys()),
        key="global_mes",
        format_func=etiqueta_mes
    )

    st.sidebar.divider()
    st.sidebar.metric("Código", codigo)
    st.sidebar.metric(
        "Superficie",
        f"{edificio['superficie_m2']:,.0f} m²"
        if pd.notna(edificio["superficie_m2"])
        else "Sin dato"
    )

    unidad_ref, valor_ref = obtener_valor_referencia(edificio)
    st.sidebar.metric("Referencia", f"{valor_ref:,.0f} {unidad_ref}" if valor_ref > 0 else "Sin dato")

    sim_activa = cargar_simulacion_activa(codigo)
    if sim_activa.empty:
        st.sidebar.warning("Sin simulación activa.")
    else:
        st.sidebar.success(f"Sim activa: {sim_activa.iloc[0]['nombre_simulacion']}")

    return codigo, edificio, int(anio), int(mes)


# ==================================================
# APP
# ==================================================

inicializar_db()

edificios_activos = cargar_edificios(False)
edificios_todos = cargar_edificios(True)

aplicar_estilos()
codigo_global, edificio_global, anio_global, mes_global = configurar_sidebar(edificios_activos)

mostrar_cabecera_app()
mostrar_mensaje_estado()

tab_inicio, tab_edificios, tab_sim, tab_bms, tab_comp, tab_informe, tab_costes, tab_co2 = st.tabs([
    "📊 Panel",
    "🏢 Edificios",
    "📈 Simulaciones",
    "📥 BMS",
    "📊 Comparativa",
    "📄 Informe mensual",
    "💰 Costes",
    "🌍 CO₂",
])


# ==================================================
# INICIO
# ==================================================

with tab_inicio:
    st.header("Panel general")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        codigo = codigo_global
        edificio = edificio_global
        anio = anio_global
        mes = mes_global

        mostrar_contexto(codigo, edificio, anio, mes)

        sim_activa = cargar_simulacion_activa(codigo)
        meses = meses_bms(codigo, anio)
        df_anio = consumos_bms_anio(codigo, anio)

        total_real = 0 if df_anio.empty else df_anio["consumo_kwh"].sum()
        etiqueta_indicador, valor_indicador, unidad_indicador = indicador_especifico(total_real, edificio)
        superficie = edificio["superficie_m2"] if pd.notna(edificio["superficie_m2"]) else 0
        kwh_m2 = 0 if superficie == 0 else total_real / superficie

        desviacion_mes = "Sin dato"
        alertas_mes = 0

        if not sim_activa.empty:
            sim_id = int(sim_activa.iloc[0]["id"])
            comp_mes = comparativa_mensual(codigo, sim_id, anio, mes)

            if not comp_mes.empty:
                total_sim_mes = comp_mes["simulado_kwh"].sum()
                total_real_mes = comp_mes["real_kwh"].sum()
                desv_mes = total_real_mes - total_sim_mes
                pct_mes = 0 if total_sim_mes == 0 else desv_mes / total_sim_mes * 100
                desviacion_mes = f"{pct_mes:.2f}%"
                alertas_mes = len(comp_mes[abs(comp_mes["desviacion_pct"]) > 10])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Meses BMS", f"{len(meses)}/12")
        c2.metric("Consumo acumulado", f"{total_real:,.0f} kWh")
        c3.metric(f"{etiqueta_indicador} acumulado", f"{valor_indicador:.2f}")
        c4.metric("Desviación mes", desviacion_mes)

        info1, info2 = st.columns([1, 1])

        with info1:
            st.subheader("Edificio")
            st.write("**Nombre:**", edificio["nombre"])
            st.write("**Cliente:**", edificio["cliente"])
            st.write("**Ubicación:**", edificio["ubicacion"])
            st.write("**Uso:**", edificio["uso"])
            st.write("**Categoría:**", edificio.get("categoria_edificio", ""))
            st.write("**Referencia:**", f"{obtener_valor_referencia(edificio)[1]:,.0f} {obtener_valor_referencia(edificio)[0]}")
            st.write("**Sistema:**", edificio["sistema_climatizacion"])

        with info2:
            st.subheader("Estado operativo")
            if sim_activa.empty:
                st.warning("No hay simulación activa.")
            else:
                st.success(f"Simulación activa: {sim_activa.iloc[0]['nombre_simulacion']}")

            if alertas_mes == 0:
                st.success("Sin alertas relevantes en el mes activo.")
            else:
                st.warning(f"{alertas_mes} categorías superan el 10% de desviación.")

            st.metric("Cobertura anual", f"{len(meses) / 12 * 100:.0f}%")

        if not df_anio.empty:
            resumen_mes = df_anio.groupby("mes").agg({
                "electricidad_kwh": "sum",
                "gas_kwh": "sum",
                "consumo_kwh": "sum",
            }).reset_index()

            st.subheader("Consumo BMS acumulado")
            st.bar_chart(resumen_mes.set_index("mes")[["electricidad_kwh", "gas_kwh"]])
            mostrar_dataframe(resumen_mes)


# ==================================================
# EDIFICIOS
# ==================================================

with tab_edificios:
    st.header("Gestión de edificios")

    sub1, sub2, sub3, sub4 = st.tabs(["Crear", "Editar", "Archivar / Reactivar", "Eliminar"])

    with sub1:
        with st.form("crear_edificio"):
            codigo = st.text_input("Código", placeholder="EDIF-2026-001")
            nombre = st.text_input("Nombre")
            cliente = st.text_input("Cliente")
            ubicacion = st.text_input("Ubicación")
            categoria_edificio = st.selectbox("Categoría de edificio", TIPOS_EDIFICIO, index=0)
            uso = st.text_input("Uso", value=categoria_edificio)
            superficie = st.number_input("Superficie m²", min_value=0.0, step=100.0)

            c_ref1, c_ref2 = st.columns(2)
            unidad_referencia = c_ref1.selectbox("Unidad principal para comparar", UNIDADES_REFERENCIA, index=0)
            valor_unidad_referencia = c_ref2.number_input("Valor de la unidad principal", min_value=0.0, step=1.0)

            c_car1, c_car2, c_car3 = st.columns(3)
            habitaciones = c_car1.number_input("Habitaciones", min_value=0.0, step=1.0)
            puestos_trabajo = c_car2.number_input("Puestos de trabajo", min_value=0.0, step=1.0)
            camas = c_car3.number_input("Camas", min_value=0.0, step=1.0)
            horario_uso = st.text_input("Horario de uso", placeholder="Ej. 24/7, laborables 8-20 h")
            sistema = st.text_input("Sistema climatización")
            obs = st.text_area("Observaciones")

            if st.form_submit_button("Crear edificio"):
                codigo = codigo.strip().upper()
                nombre = nombre.strip()

                if codigo == "" or nombre == "":
                    st.error("Código y nombre son obligatorios.")
                elif codigo in edificios_todos["codigo_proyecto"].values:
                    st.error("Ya existe ese código.")
                else:
                    guardar_edificio({
                        "codigo_proyecto": codigo,
                        "nombre": nombre,
                        "cliente": cliente,
                        "ubicacion": ubicacion,
                        "uso": uso,
                        "superficie_m2": superficie,
                        "categoria_edificio": categoria_edificio,
                        "unidad_referencia": unidad_referencia,
                        "valor_unidad_referencia": valor_unidad_referencia,
                        "habitaciones": habitaciones,
                        "puestos_trabajo": puestos_trabajo,
                        "camas": camas,
                        "horario_uso": horario_uso,
                        "sistema_climatizacion": sistema,
                        "observaciones": obs,
                    })
                    carpeta = crear_carpetas_edificio(codigo, nombre)
                    st.info(carpeta)
                    guardar_mensaje_y_recargar("Edificio creado.")

    with sub2:
        if edificios_todos.empty:
            st.warning("No hay edificios.")
        else:
            opcion = st.selectbox(
                "Edificio",
                edificios_todos["codigo_proyecto"] + " - " + edificios_todos["nombre"],
                key="editar_edificio"
            )
            codigo = opcion.split(" - ")[0]
            edificio = edificios_todos[edificios_todos["codigo_proyecto"] == codigo].iloc[0]

            with st.form("editar_edificio"):
                nombre = st.text_input("Nombre", value=edificio["nombre"])
                cliente = st.text_input("Cliente", value=edificio["cliente"] or "")
                ubicacion = st.text_input("Ubicación", value=edificio["ubicacion"] or "")
                categoria_actual = edificio.get("categoria_edificio", edificio["uso"] or "Oficinas")
                idx_categoria = TIPOS_EDIFICIO.index(categoria_actual) if categoria_actual in TIPOS_EDIFICIO else 0
                categoria_edificio = st.selectbox("Categoría de edificio", TIPOS_EDIFICIO, index=idx_categoria)
                uso = st.text_input("Uso", value=edificio["uso"] or categoria_edificio)
                superficie = st.number_input(
                    "Superficie m²",
                    min_value=0.0,
                    step=100.0,
                    value=float(edificio["superficie_m2"]) if pd.notna(edificio["superficie_m2"]) else 0.0
                )

                unidad_actual = edificio.get("unidad_referencia", "m²")
                idx_unidad = UNIDADES_REFERENCIA.index(unidad_actual) if unidad_actual in UNIDADES_REFERENCIA else 0
                c_ref1, c_ref2 = st.columns(2)
                unidad_referencia = c_ref1.selectbox("Unidad principal para comparar", UNIDADES_REFERENCIA, index=idx_unidad)
                valor_unidad_referencia = c_ref2.number_input(
                    "Valor de la unidad principal",
                    min_value=0.0,
                    step=1.0,
                    value=float(edificio.get("valor_unidad_referencia", 0) or 0),
                )

                c_car1, c_car2, c_car3 = st.columns(3)
                habitaciones = c_car1.number_input("Habitaciones", min_value=0.0, step=1.0, value=float(edificio.get("habitaciones", 0) or 0))
                puestos_trabajo = c_car2.number_input("Puestos de trabajo", min_value=0.0, step=1.0, value=float(edificio.get("puestos_trabajo", 0) or 0))
                camas = c_car3.number_input("Camas", min_value=0.0, step=1.0, value=float(edificio.get("camas", 0) or 0))
                horario_uso = st.text_input("Horario de uso", value=edificio.get("horario_uso", "") or "")
                sistema = st.text_input("Sistema climatización", value=edificio["sistema_climatizacion"] or "")
                obs = st.text_area("Observaciones", value=edificio["observaciones"] or "")

                if st.form_submit_button("Guardar cambios"):
                    actualizar_edificio(codigo, {
                        "nombre": nombre,
                        "cliente": cliente,
                        "ubicacion": ubicacion,
                        "uso": uso,
                        "superficie_m2": superficie,
                        "categoria_edificio": categoria_edificio,
                        "unidad_referencia": unidad_referencia,
                        "valor_unidad_referencia": valor_unidad_referencia,
                        "habitaciones": habitaciones,
                        "puestos_trabajo": puestos_trabajo,
                        "camas": camas,
                        "horario_uso": horario_uso,
                        "sistema_climatizacion": sistema,
                        "observaciones": obs,
                    })
                    crear_carpetas_edificio(codigo, nombre)
                    guardar_mensaje_y_recargar("Edificio actualizado.")

    with sub3:
        mostrar_dataframe(edificios_todos)

        if not edificios_todos.empty:
            opcion = st.selectbox(
                "Edificio",
                edificios_todos["codigo_proyecto"] + " - " + edificios_todos["nombre"],
                key="estado_edificio"
            )
            codigo = opcion.split(" - ")[0]

            c1, c2 = st.columns(2)

            with c1:
                if st.button("Archivar"):
                    cambiar_estado_edificio(codigo, "ARCHIVADO")
                    guardar_mensaje_y_recargar("Edificio archivado.")

            with c2:
                if st.button("Reactivar"):
                    cambiar_estado_edificio(codigo, "ACTIVO")
                    guardar_mensaje_y_recargar("Edificio reactivado.")

    with sub4:
        st.warning(
            "Eliminar un proyecto borra definitivamente el edificio y sus datos de "
            "simulaciones/BMS en la base de datos. Las carpetas y archivos guardados se conservan."
        )

        if edificios_todos.empty:
            st.warning("No hay edificios para eliminar.")
        else:
            opcion = st.selectbox(
                "Proyecto a eliminar",
                edificios_todos["codigo_proyecto"] + " - " + edificios_todos["nombre"],
                key="eliminar_edificio"
            )
            codigo = opcion.split(" - ")[0]
            edificio = edificios_todos[edificios_todos["codigo_proyecto"] == codigo].iloc[0]
            resumen = resumen_datos_edificio(codigo)

            st.write("**Proyecto:**", edificio["nombre"])
            st.write("**Cliente:**", edificio["cliente"])
            st.write("**Estado:**", edificio["estado"])

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Simulaciones", resumen["simulaciones"])
            c2.metric("Filas simulación", resumen["detalle_simulaciones"])
            c3.metric("BMS importados", resumen["consumos_bms"])
            c4.metric("Filas BMS", resumen["detalle_bms"])

            confirmacion = st.text_input(
                f"Escribe {codigo} para confirmar",
                key="confirmar_eliminar_edificio"
            )
            acepta = st.checkbox(
                "Entiendo que esta acción no se puede deshacer.",
                key="aceptar_eliminar_edificio"
            )
            puede_eliminar = acepta and confirmacion.strip().upper() == codigo

            if st.button(
                "Eliminar proyecto definitivamente",
                disabled=not puede_eliminar,
                type="primary"
            ):
                eliminados = eliminar_edificio(codigo)
                guardar_mensaje_y_recargar(
                    "Proyecto eliminado. "
                    f"Se borraron {eliminados['simulaciones']} simulaciones y "
                    f"{eliminados['consumos_bms']} importaciones BMS."
                )


# ==================================================
# SIMULACIONES
# ==================================================

with tab_sim:
    st.header("Simulaciones DesignBuilder")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        codigo = codigo_global
        edificio = edificio_global
        mostrar_contexto(codigo, edificio, anio_global)

        with st.form("importar_sim"):
            nombre = st.text_input("Nombre simulación", value="Simulación DesignBuilder")
            desc = st.text_area("Descripción")
            anio = st.number_input("Año", 2000, 2100, anio_global, key="sim_anio")
            activa = st.checkbox("Marcar como activa", value=True)
            archivo = st.file_uploader("Archivo .dat", type=["dat", "txt"])

            if st.form_submit_button("Importar simulación"):
                if archivo is None:
                    st.error("Sube un archivo .dat.")
                else:
                    df, ignoradas, errores = transformar_dat_designbuilder(archivo, anio)

                    if errores:
                        for e in errores:
                            st.error(e)
                        st.write(ignoradas)
                    else:
                        sim_id = crear_simulacion(codigo, nombre, desc, activa)
                        guardar_detalle_simulacion(sim_id, df)

                        carpeta = crear_carpetas_edificio(codigo, edificio["nombre"])
                        ruta = os.path.join(carpeta, "simulaciones", f"simulacion_{sim_id}.dat")

                        with open(ruta, "wb") as f:
                            f.write(archivo.getbuffer())

                        st.success("Simulación importada.")
                        mostrar_dataframe(df)

                        if ignoradas:
                            st.warning("Categorías ignoradas:")
                            st.write(ignoradas)

        sims = cargar_simulaciones(codigo)

        st.subheader("Simulaciones existentes")

        if sims.empty:
            st.warning("No hay simulaciones.")
        else:
            mostrar_dataframe(sims)

            opcion_sim = st.selectbox(
                "Ver detalle",
                [f"{r['id']} - {r['nombre_simulacion']}" for _, r in sims.iterrows()]
            )
            sim_id = int(opcion_sim.split(" - ")[0])
            detalle = cargar_detalle_simulacion(sim_id)

            mostrar_dataframe(detalle)

            if not detalle.empty:
                resumen = detalle.groupby("categoria")["consumo_kwh"].sum().reset_index()
                st.bar_chart(resumen.set_index("categoria")["consumo_kwh"])

            if st.button("Marcar como activa"):
                marcar_simulacion_activa(sim_id, codigo)
                guardar_mensaje_y_recargar("Simulación marcada como activa.")


# ==================================================
# BMS
# ==================================================

with tab_bms:
    st.header("Consumos reales BMS")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        codigo = codigo_global
        edificio = edificio_global
        anio = anio_global
        mes = mes_global
        mostrar_contexto(codigo, edificio, anio, mes)

        modo = st.radio("Modo", ["Un mes", "Varios meses"], horizontal=True)

        if modo == "Un mes":
            with st.form("bms_un_mes"):
                nombre = st.text_input("Nombre importación", value=f"BMS {anio}-{mes:02d}")
                desc = st.text_area("Descripción")
                archivo = st.file_uploader("CSV BMS", type=["csv"])

                if st.form_submit_button("Importar BMS"):
                    if archivo is None:
                        st.error("Sube un CSV.")
                    else:
                        df, errores = transformar_csv_bms(archivo)

                        if errores:
                            for e in errores:
                                st.error(e)
                        else:
                            bms_id = crear_consumo_bms(codigo, anio, mes, nombre, desc)
                            guardar_detalle_bms(bms_id, df)

                            carpeta = crear_carpetas_edificio(codigo, edificio["nombre"])
                            ruta = os.path.join(carpeta, "consumos_bms", f"bms_{anio}_{mes:02d}_{bms_id}.csv")

                            with open(ruta, "wb") as f:
                                f.write(archivo.getbuffer())

                            st.success("BMS importado.")
                            mostrar_dataframe(df)

        else:
            archivos = st.file_uploader("CSV BMS", type=["csv"], accept_multiple_files=True)

            if archivos:
                asignaciones = []

                for i, archivo in enumerate(archivos):
                    c1, c2 = st.columns([3, 1])
                    c1.write(archivo.name)
                    mes = c2.selectbox("Mes", list(range(1, 13)), key=f"mes_bms_{i}")
                    asignaciones.append((archivo, mes))

                if st.button("Importar todos"):
                    importados = 0

                    for archivo, mes in asignaciones:
                        df, errores = transformar_csv_bms(archivo)

                        if errores:
                            st.error(f"{archivo.name}: {errores}")
                            continue

                        bms_id = crear_consumo_bms(
                            codigo,
                            anio,
                            mes,
                            f"BMS {anio}-{mes:02d} - {archivo.name}",
                            "Carga múltiple"
                        )
                        guardar_detalle_bms(bms_id, df)

                        carpeta = crear_carpetas_edificio(codigo, edificio["nombre"])
                        ruta = os.path.join(carpeta, "consumos_bms", f"bms_{anio}_{mes:02d}_{bms_id}_{archivo.name}")

                        with open(ruta, "wb") as f:
                            f.write(archivo.getbuffer())

                        importados += 1

                    st.success(f"Importados: {importados}")

        st.subheader("BMS existentes")

        bms = cargar_consumos_bms(codigo)

        if bms.empty:
            st.warning("No hay consumos BMS.")
        else:
            mostrar_dataframe(bms)

            opcion_bms = st.selectbox(
                "Ver detalle",
                [f"{r['id']} - {r['anio']}-{int(r['mes']):02d} - {r['nombre_importacion']}" for _, r in bms.iterrows()]
            )

            bms_id = int(opcion_bms.split(" - ")[0])
            detalle = cargar_detalle_bms(bms_id)

            mostrar_dataframe(detalle)


# ==================================================
# COMPARATIVA
# ==================================================

with tab_comp:
    st.header("Comparativa Simulación vs BMS")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        codigo = codigo_global
        edificio = edificio_global
        anio = anio_global
        mes = mes_global
        mostrar_contexto(codigo, edificio, anio, mes)

        sim_activa = cargar_simulacion_activa(codigo)

        if sim_activa.empty:
            st.warning("No hay simulación activa.")
        else:
            sim_id = int(sim_activa.iloc[0]["id"])
            st.success(f"Simulación activa: {sim_activa.iloc[0]['nombre_simulacion']}")

            subt1, subt2, subt3 = st.tabs(["Mensual", "Acumulada", "Base comparable"])

            with subt1:
                comp = comparativa_mensual(codigo, sim_id, anio, mes)

                if comp.empty:
                    st.warning("No hay BMS cargado para este mes.")
                else:
                    total_sim = comp["simulado_kwh"].sum()
                    total_real = comp["real_kwh"].sum()
                    desv = total_real - total_sim
                    pct = 0 if total_sim == 0 else desv / total_sim * 100
                    etiqueta_indicador, valor_indicador, _ = indicador_especifico(total_real, edificio)

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Simulado", f"{total_sim:,.0f} kWh")
                    c2.metric("Real BMS", f"{total_real:,.0f} kWh")
                    c3.metric("Desviación", f"{pct:.2f}%", f"{desv:,.0f} kWh")
                    c4.metric(etiqueta_indicador, f"{valor_indicador:.2f}")

                    st.subheader("Lectura rápida")
                    g1, g2 = st.columns([1, 1])
                    with g1:
                        grafico_barras_comparativa(comp, "Simulado frente a real por categoría")
                    with g2:
                        grafico_desviacion(comp, "Desviación por categoría")

                    grafico_pareto_desviaciones(comp, "Qué categorías explican la desviación")

                    st.subheader("Detalle")
                    mostrar_dataframe(comp)

            with subt2:
                df_meses, df_cat = comparativa_parcial_anual(codigo, sim_id, anio)

                if df_meses.empty:
                    st.warning("No hay BMS cargado para este año.")
                else:
                    meses_cargados = len(df_meses)
                    cobertura = meses_cargados / 12 * 100
                    total_sim = df_meses["simulado_kwh"].sum()
                    total_real = df_meses["real_kwh"].sum()
                    desv = total_real - total_sim
                    pct = 0 if total_sim == 0 else desv / total_sim * 100
                    proy = total_real / meses_cargados * 12
                    etiqueta_indicador, valor_indicador, _ = indicador_especifico(total_real, edificio)

                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Meses BMS", f"{meses_cargados}/12")
                    c2.metric("Cobertura", f"{cobertura:.0f}%")
                    c3.metric("Desviación acumulada", f"{pct:.2f}%", f"{desv:,.0f} kWh")
                    c4.metric("Proyección anual", f"{proy:,.0f} kWh")
                    c5.metric(f"{etiqueta_indicador} acum.", f"{valor_indicador:.2f}")

                    grafico_evolucion_mensual(df_meses, "Evolución mensual: simulado, real y desviación")

                    st.subheader("Categorías acumuladas")
                    g1, g2 = st.columns([1, 1])
                    with g1:
                        grafico_barras_comparativa(df_cat, "Acumulado por categoría")
                    with g2:
                        grafico_desviacion(df_cat, "Desviación acumulada por categoría")

                    st.subheader("Resumen mensual")
                    mostrar_dataframe(df_meses)

                    st.subheader("Detalle por categoría")
                    mostrar_dataframe(df_cat)

            with subt3:
                st.subheader("Base comparable de edificios")
                st.caption(
                    "Esta vista empieza a construir una base de datos útil para comparar edificios similares. "
                    "Cada edificio puede usar una unidad de referencia distinta: m², habitaciones, puestos, camas, usuarios u otra."
                )

                filas = []
                for _, edif in edificios_todos.iterrows():
                    df_edif = consumos_bms_anio(edif["codigo_proyecto"], anio)
                    total = 0 if df_edif.empty else df_edif["consumo_kwh"].sum()
                    etiqueta, indicador, unidad = indicador_especifico(total, edif)
                    unidad_ref, valor_ref = obtener_valor_referencia(edif)
                    filas.append({
                        "codigo_proyecto": edif["codigo_proyecto"],
                        "nombre": edif["nombre"],
                        "categoria_edificio": edif.get("categoria_edificio", edif.get("uso", "")),
                        "superficie_m2": edif.get("superficie_m2", 0),
                        "unidad_referencia": unidad_ref,
                        "valor_unidad_referencia": valor_ref,
                        "consumo_kwh": total,
                        "indicador_especifico": indicador,
                        "unidad_indicador": etiqueta,
                    })

                df_base = pd.DataFrame(filas)
                df_base = df_base[df_base["consumo_kwh"] > 0].copy()

                if df_base.empty:
                    st.warning("Todavía no hay consumos anuales suficientes para comparar edificios.")
                else:
                    categorias = sorted(df_base["categoria_edificio"].dropna().unique().tolist())
                    categoria_sel = st.multiselect("Filtrar por categoría", categorias, default=categorias)
                    df_filtrado = df_base[df_base["categoria_edificio"].isin(categoria_sel)] if categoria_sel else df_base

                    grafico_ranking_indicadores(
                        df_filtrado,
                        "Ranking de consumo específico para edificios comparables"
                    )
                    mostrar_dataframe(df_filtrado.sort_values(["categoria_edificio", "indicador_especifico"]))


# ==================================================
# INFORME MENSUAL
# ==================================================

with tab_informe:
    st.header("Informe mensual")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        codigo = codigo_global
        edificio = edificio_global
        anio = anio_global
        mes = mes_global
        mostrar_contexto(codigo, edificio, anio, mes)

        sim_activa = cargar_simulacion_activa(codigo)

        if sim_activa.empty:
            st.warning("No hay simulación activa.")
        else:
            sim_id = int(sim_activa.iloc[0]["id"])
            comp = comparativa_mensual(codigo, sim_id, anio, mes)

            if comp.empty:
                st.warning("No hay BMS cargado para este mes.")
            else:
                total_sim = comp["simulado_kwh"].sum()
                total_real = comp["real_kwh"].sum()
                desv = total_real - total_sim
                pct = 0 if total_sim == 0 else desv / total_sim * 100
                etiqueta_indicador, valor_indicador, _ = indicador_especifico(total_real, edificio)

                alertas = comp[abs(comp["desviacion_pct"]) > 10].copy()
                observaciones = generar_observaciones(comp)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Simulado", f"{total_sim:,.0f} kWh")
                c2.metric("Real BMS", f"{total_real:,.0f} kWh")
                c3.metric("Desviación", f"{pct:.2f}%")
                c4.metric(f"{etiqueta_indicador} mes", f"{valor_indicador:.2f}")

                st.subheader("Alertas")
                if alertas.empty:
                    st.success("No se detectan desviaciones relevantes superiores al 10%.")
                else:
                    mostrar_dataframe(alertas[["categoria", "simulado_kwh", "real_kwh", "desviacion_pct", "estado"]])

                st.subheader("Comparativa")
                mostrar_dataframe(comp)

                st.subheader("Observaciones")
                st.markdown(observaciones)

                alertas_txt = "No se detectan alertas relevantes."
                if not alertas.empty:
                    alertas_txt = "\n".join(
                        f"{r['estado']} {r['categoria']}: {r['desviacion_pct']:.2f}%"
                        for _, r in alertas.iterrows()
                    )

                texto = f"""
INFORME MENSUAL ENERGÉTICO

Proyecto: {edificio['nombre']}
Código: {edificio['codigo_proyecto']}
Cliente: {edificio['cliente']}
Ubicación: {edificio['ubicacion']}
Periodo analizado: {mes}/{anio}

RESUMEN EJECUTIVO

Consumo simulado: {total_sim:,.0f} kWh
Consumo real BMS: {total_real:,.0f} kWh
Desviación: {desv:,.0f} kWh
Desviación porcentual: {pct:.2f} %
Indicador específico mensual: {valor_indicador:.2f} {etiqueta_indicador} mes

ALERTAS DETECTADAS

{alertas_txt}

OBSERVACIONES TÉCNICAS

{observaciones}
"""

                st.text_area("Texto base del informe", texto, height=350)

                st.download_button(
                    "Descargar TXT",
                    data=texto,
                    file_name=f"informe_{codigo}_{anio}_{mes:02d}.txt",
                    mime="text/plain"
                )


# ==================================================
# COSTES
# ==================================================

with tab_costes:
    st.header("Costes energéticos")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        codigo = codigo_global
        edificio = edificio_global
        anio = anio_global
        mostrar_contexto(codigo, edificio, anio)

        c1, c2 = st.columns(2)
        precio_elec = c1.number_input("Precio electricidad €/kWh", min_value=0.0, value=0.18, step=0.01)
        precio_gas = c2.number_input("Precio gas natural €/kWh", min_value=0.0, value=0.07, step=0.01)

        df = consumos_bms_anio(codigo, anio)

        if df.empty:
            st.warning("No hay BMS cargado para este año.")
        else:
            df["coste_electricidad_eur"] = df["electricidad_kwh"] * precio_elec
            df["coste_gas_eur"] = df["gas_kwh"] * precio_gas
            df["coste_total_eur"] = df["coste_electricidad_eur"] + df["coste_gas_eur"]

            resumen_mes = df.groupby("mes").agg({
                "electricidad_kwh": "sum",
                "gas_kwh": "sum",
                "consumo_kwh": "sum",
                "coste_electricidad_eur": "sum",
                "coste_gas_eur": "sum",
                "coste_total_eur": "sum",
            }).reset_index()

            resumen_cat = df.groupby("categoria").agg({
                "electricidad_kwh": "sum",
                "gas_kwh": "sum",
                "consumo_kwh": "sum",
                "coste_total_eur": "sum",
            }).reset_index().sort_values("coste_total_eur", ascending=False)

            meses_cargados = resumen_mes["mes"].nunique()
            coste_total = resumen_mes["coste_total_eur"].sum()
            superficie = edificio["superficie_m2"] if pd.notna(edificio["superficie_m2"]) else 0
            coste_m2 = 0 if superficie == 0 else coste_total / superficie
            proy = 0 if meses_cargados == 0 else coste_total / meses_cargados * 12

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Meses BMS", f"{meses_cargados}/12")
            c2.metric("Coste acumulado", f"{coste_total:,.0f} €")
            c3.metric("Coste €/m²", f"{coste_m2:.2f} €/m²")
            c4.metric("Proyección anual", f"{proy:,.0f} €")

            st.subheader("Coste mensual")
            mostrar_dataframe(resumen_mes)
            st.bar_chart(resumen_mes.set_index("mes")[["coste_electricidad_eur", "coste_gas_eur"]])

            st.subheader("Coste por categoría")
            mostrar_dataframe(resumen_cat)


# ==================================================
# CO2
# ==================================================

with tab_co2:
    st.header("Emisiones CO₂")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        codigo = codigo_global
        edificio = edificio_global
        anio = anio_global
        mostrar_contexto(codigo, edificio, anio)

        c1, c2 = st.columns(2)
        factor_elec = c1.number_input("Electricidad kgCO₂/kWh", min_value=0.0, value=0.18, step=0.01)
        factor_gas = c2.number_input("Gas natural kgCO₂/kWh", min_value=0.0, value=0.20, step=0.01)

        df = consumos_bms_anio(codigo, anio)

        if df.empty:
            st.warning("No hay BMS cargado para este año.")
        else:
            df["co2_electricidad_kg"] = df["electricidad_kwh"] * factor_elec
            df["co2_gas_kg"] = df["gas_kwh"] * factor_gas
            df["co2_total_kg"] = df["co2_electricidad_kg"] + df["co2_gas_kg"]

            resumen_mes = df.groupby("mes").agg({
                "electricidad_kwh": "sum",
                "gas_kwh": "sum",
                "co2_electricidad_kg": "sum",
                "co2_gas_kg": "sum",
                "co2_total_kg": "sum",
            }).reset_index()

            resumen_cat = df.groupby("categoria").agg({
                "co2_total_kg": "sum",
                "electricidad_kwh": "sum",
                "gas_kwh": "sum",
            }).reset_index().sort_values("co2_total_kg", ascending=False)

            meses_cargados = resumen_mes["mes"].nunique()
            co2_total_kg = resumen_mes["co2_total_kg"].sum()
            co2_tn = co2_total_kg / 1000
            superficie = edificio["superficie_m2"] if pd.notna(edificio["superficie_m2"]) else 0
            co2_m2 = 0 if superficie == 0 else co2_total_kg / superficie
            proy_tn = 0 if meses_cargados == 0 else co2_tn / meses_cargados * 12

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Meses BMS", f"{meses_cargados}/12")
            c2.metric("CO₂ acumulado", f"{co2_tn:,.2f} tCO₂")
            c3.metric("kgCO₂/m²", f"{co2_m2:.2f}")
            c4.metric("Proyección anual", f"{proy_tn:,.2f} tCO₂")

            st.subheader("CO₂ mensual")
            mostrar_dataframe(resumen_mes)
            st.bar_chart(resumen_mes.set_index("mes")[["co2_electricidad_kg", "co2_gas_kg"]])

            st.subheader("CO₂ por categoría")
            mostrar_dataframe(resumen_cat)
