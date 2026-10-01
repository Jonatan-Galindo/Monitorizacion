import os
import re
import sqlite3
from io import StringIO

import pandas as pd
import streamlit as st

DB = "database.db"
CARPETA_BASE = "datos_edificios"

st.set_page_config(page_title="PGI Energía", layout="wide")


# =========================
# BASE
# =========================

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

    raise Exception("No se pudo leer el CSV.")


# =========================
# EDIFICIOS
# =========================

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
            superficie_m2, sistema_climatizacion, estado, observaciones
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVO', ?)
    """, (
        datos["codigo_proyecto"],
        datos["nombre"],
        datos["cliente"],
        datos["ubicacion"],
        datos["uso"],
        datos["superficie_m2"],
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
            sistema_climatizacion=?, observaciones=?
        WHERE codigo_proyecto=?
    """, (
        datos["nombre"],
        datos["cliente"],
        datos["ubicacion"],
        datos["uso"],
        datos["superficie_m2"],
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


# =========================
# SIMULACIONES DESIGNBUILDER
# =========================

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

    df = pd.read_csv(
        StringIO(texto),
        sep="\t",
        decimal=",",
        header=0,
        engine="python"
    )

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
            sim_id,
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
        params=(sim_id,)
    )
    conn.close()
    return df


def marcar_simulacion_activa(sim_id, codigo):
    conn = conectar_db()
    c = conn.cursor()
    c.execute("UPDATE simulaciones SET activa=0 WHERE codigo_proyecto=?", (codigo,))
    c.execute("UPDATE simulaciones SET activa=1 WHERE id=?", (sim_id,))
    conn.commit()
    conn.close()


# =========================
# BMS
# =========================

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
                consumo_bms_id, categoria, consumo_kwh, nombre_original_bms
            )
            VALUES (?, ?, ?, ?)
        """, (
            bms_id,
            fila["categoria"],
            float(fila["consumo_kwh"]),
            fila["nombre_original_bms"],
        ))

    conn.commit()
    conn.close()


def cargar_consumos_bms(codigo):
    conn = conectar_db()
    df = pd.read_sql_query(
        "SELECT * FROM consumos_bms WHERE codigo_proyecto=? ORDER BY anio DESC, mes DESC",
        conn,
        params=(codigo,)
    )
    conn.close()
    return df


def cargar_detalle_bms(bms_id):
    conn = conectar_db()
    df = pd.read_sql_query(
        "SELECT * FROM consumo_bms_detalle WHERE consumo_bms_id=? ORDER BY categoria",
        conn,
        params=(bms_id,)
    )
    conn.close()
    return df


def cargar_bms_mes(codigo, anio, mes):
    conn = conectar_db()

    cabecera = pd.read_sql_query(
        """
        SELECT * FROM consumos_bms
        WHERE codigo_proyecto=? AND anio=? AND mes=?
        ORDER BY fecha_importacion DESC
        LIMIT 1
        """,
        conn,
        params=(codigo, int(anio), int(mes))
    )

    if cabecera.empty:
        conn.close()
        return pd.DataFrame()

    bms_id = int(cabecera.iloc[0]["id"])

    df = pd.read_sql_query(
        """
        SELECT categoria, consumo_kwh
        FROM consumo_bms_detalle
        WHERE consumo_bms_id=?
        """,
        conn,
        params=(bms_id,)
    )

    conn.close()
    return df


# =========================
# APP
# =========================

inicializar_db()

edificios_activos = cargar_edificios(False)
edificios_todos = cargar_edificios(True)

st.title("🏢 PGI Energía")

tab_dashboard, tab_edificios, tab_sim, tab_bms, tab_info = st.tabs([
    "📊 Dashboard",
    "🏢 Edificios",
    "📈 Simulaciones",
    "📥 Consumos BMS",
    "📁 Estructura"
])


# =========================
# DASHBOARD
# =========================

with tab_dashboard:
    st.header("Dashboard")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        opcion = st.selectbox(
            "Edificio",
            edificios_activos["codigo_proyecto"] + " - " + edificios_activos["nombre"],
            key="dash_edificio"
        )

        codigo = opcion.split(" - ")[0]
        edificio = edificios_activos[edificios_activos["codigo_proyecto"] == codigo].iloc[0]

        st.subheader("Ficha")
        c1, c2, c3 = st.columns(3)
        c1.metric("Código", edificio["codigo_proyecto"])
        c2.metric("Uso", edificio["uso"])
        c3.metric("Superficie m²", f"{edificio['superficie_m2']:,.0f}")

        st.write("**Nombre:**", edificio["nombre"])
        st.write("**Cliente:**", edificio["cliente"])
        st.write("**Ubicación:**", edificio["ubicacion"])
        st.write("**Sistema climatización:**", edificio["sistema_climatizacion"])

        sim_activa = cargar_simulacion_activa(codigo)

        if sim_activa.empty:
            st.warning("No hay simulación activa.")
        else:
            sim = sim_activa.iloc[0]
            st.success(f"Simulación activa: {sim['nombre_simulacion']}")

            anio = st.number_input("Año", 2000, 2100, 2026, key="dash_anio")
            mes = st.selectbox("Mes", list(range(1, 13)), key="dash_mes")

            sim_det = cargar_detalle_simulacion(sim["id"])
            sim_mes = sim_det[
                (sim_det["anio"] == int(anio)) &
                (sim_det["mes"] == int(mes))
            ][["categoria", "consumo_kwh"]].rename(columns={"consumo_kwh": "simulado_kwh"})

            bms_mes = cargar_bms_mes(codigo, anio, mes)

            if bms_mes.empty:
                st.warning("No hay BMS cargado para ese mes.")
            else:
                bms_mes = bms_mes.rename(columns={"consumo_kwh": "real_kwh"})

                comp = pd.merge(sim_mes, bms_mes, on="categoria", how="outer").fillna(0)
                comp["desviacion_kwh"] = comp["real_kwh"] - comp["simulado_kwh"]
                comp["desviacion_pct"] = comp.apply(
                    lambda r: 0 if r["simulado_kwh"] == 0 else round(r["desviacion_kwh"] / r["simulado_kwh"] * 100, 2),
                    axis=1
                )

                st.dataframe(comp, use_container_width=True)

                total_sim = comp["simulado_kwh"].sum()
                total_real = comp["real_kwh"].sum()
                pct = 0 if total_sim == 0 else (total_real - total_sim) / total_sim * 100

                c1, c2, c3 = st.columns(3)
                c1.metric("Simulado kWh", f"{total_sim:,.0f}")
                c2.metric("Real BMS kWh", f"{total_real:,.0f}")
                c3.metric("Desviación %", f"{pct:.2f}%")

                st.bar_chart(comp.set_index("categoria")[["simulado_kwh", "real_kwh"]])


# =========================
# EDIFICIOS
# =========================

with tab_edificios:
    st.header("Gestión de edificios")

    subt1, subt2, subt3 = st.tabs(["Crear", "Editar", "Archivar/Reactivar"])

    with subt1:
        with st.form("crear_edificio"):
            codigo = st.text_input("Código PGI", placeholder="PGI-2026-001")
            nombre = st.text_input("Nombre")
            cliente = st.text_input("Cliente")
            ubicacion = st.text_input("Ubicación")
            uso = st.text_input("Uso", value="Oficinas")
            superficie = st.number_input("Superficie m²", min_value=0.0, step=100.0)
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
                        "sistema_climatizacion": sistema,
                        "observaciones": obs,
                    })
                    carpeta = crear_carpetas_edificio(codigo, nombre)
                    st.success("Edificio creado.")
                    st.info(carpeta)
                    st.warning("Recarga la página.")

    with subt2:
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

            with st.form("editar_edificio_form"):
                nombre = st.text_input("Nombre", value=edificio["nombre"])
                cliente = st.text_input("Cliente", value=edificio["cliente"] or "")
                ubicacion = st.text_input("Ubicación", value=edificio["ubicacion"] or "")
                uso = st.text_input("Uso", value=edificio["uso"] or "")
                superficie = st.number_input(
                    "Superficie m²",
                    min_value=0.0,
                    step=100.0,
                    value=float(edificio["superficie_m2"]) if pd.notna(edificio["superficie_m2"]) else 0.0
                )
                sistema = st.text_input("Sistema climatización", value=edificio["sistema_climatizacion"] or "")
                obs = st.text_area("Observaciones", value=edificio["observaciones"] or "")

                if st.form_submit_button("Guardar cambios"):
                    actualizar_edificio(codigo, {
                        "nombre": nombre,
                        "cliente": cliente,
                        "ubicacion": ubicacion,
                        "uso": uso,
                        "superficie_m2": superficie,
                        "sistema_climatizacion": sistema,
                        "observaciones": obs,
                    })
                    crear_carpetas_edificio(codigo, nombre)
                    st.success("Actualizado.")
                    st.warning("Recarga la página.")

    with subt3:
        st.dataframe(edificios_todos, use_container_width=True)

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
                    st.success("Archivado.")
                    st.warning("Recarga la página.")

            with c2:
                if st.button("Reactivar"):
                    cambiar_estado_edificio(codigo, "ACTIVO")
                    st.success("Reactivado.")
                    st.warning("Recarga la página.")


# =========================
# SIMULACIONES
# =========================

with tab_sim:
    st.header("Simulaciones DesignBuilder")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        opcion = st.selectbox(
            "Edificio",
            edificios_activos["codigo_proyecto"] + " - " + edificios_activos["nombre"],
            key="sim_edificio"
        )
        codigo = opcion.split(" - ")[0]
        edificio = edificios_activos[edificios_activos["codigo_proyecto"] == codigo].iloc[0]

        with st.form("importar_sim"):
            nombre = st.text_input("Nombre simulación", value="Simulación DesignBuilder")
            desc = st.text_area("Descripción")
            anio = st.number_input("Año", 2000, 2100, 2026)
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
                        st.dataframe(df, use_container_width=True)

                        if ignoradas:
                            st.warning("Categorías ignoradas:")
                            st.write(ignoradas)

        sims = cargar_simulaciones(codigo)

        st.subheader("Simulaciones existentes")

        if sims.empty:
            st.warning("No hay simulaciones.")
        else:
            st.dataframe(sims, use_container_width=True)

            opcion_sim = st.selectbox(
                "Ver detalle",
                [f"{r['id']} - {r['nombre_simulacion']}" for _, r in sims.iterrows()]
            )
            sim_id = int(opcion_sim.split(" - ")[0])
            detalle = cargar_detalle_simulacion(sim_id)

            st.dataframe(detalle, use_container_width=True)

            if not detalle.empty:
                resumen = detalle.groupby("categoria")["consumo_kwh"].sum().reset_index()
                st.bar_chart(resumen.set_index("categoria")["consumo_kwh"])

            if st.button("Marcar como activa"):
                marcar_simulacion_activa(sim_id, codigo)
                st.success("Marcada como activa.")
                st.warning("Recarga la página.")


# =========================
# CONSUMOS BMS
# =========================

with tab_bms:
    st.header("Consumos reales BMS")

    if edificios_activos.empty:
        st.warning("No hay edificios activos.")
    else:
        opcion = st.selectbox(
            "Edificio",
            edificios_activos["codigo_proyecto"] + " - " + edificios_activos["nombre"],
            key="bms_edificio"
        )
        codigo = opcion.split(" - ")[0]
        edificio = edificios_activos[edificios_activos["codigo_proyecto"] == codigo].iloc[0]

        modo = st.radio("Modo", ["Un mes", "Varios meses"], horizontal=True)
        anio = st.number_input("Año", 2000, 2100, 2026, key="bms_anio")

        if modo == "Un mes":
            mes = st.selectbox("Mes", list(range(1, 13)))

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
                            st.dataframe(df, use_container_width=True)

        else:
            archivos = st.file_uploader(
                "CSV BMS",
                type=["csv"],
                accept_multiple_files=True
            )

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
            st.dataframe(bms, use_container_width=True)

            opcion_bms = st.selectbox(
                "Ver detalle",
                [f"{r['id']} - {r['anio']}-{int(r['mes']):02d} - {r['nombre_importacion']}" for _, r in bms.iterrows()]
            )

            bms_id = int(opcion_bms.split(" - ")[0])
            detalle = cargar_detalle_bms(bms_id)

            st.dataframe(detalle, use_container_width=True)

            if not detalle.empty:
                resumen = detalle.groupby("categoria")["consumo_kwh"].sum().reset_index()
                st.bar_chart(resumen.set_index("categoria")["consumo_kwh"])


# =========================
# ESTRUCTURA
# =========================

with tab_info:
    st.header("Estructura")

    st.code("""
C:\\PGI_APP_ENERGIA
│
├── app.py
├── database.db
│
└── datos_edificios
    └── PGI-2026-001_nombre_edificio
        ├── simulaciones
        ├── consumos_bms
        └── informes
    """)

    st.success("Edificios, simulaciones y BMS se guardan en SQLite.")