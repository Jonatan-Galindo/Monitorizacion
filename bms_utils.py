import pandas as pd
import re
from io import StringIO


# =====================================================
# UTILIDADES
# =====================================================

def leer_texto_archivo(archivo):

    contenido = archivo.getvalue()

    codificaciones = [
        "utf-8-sig",
        "utf-8",
        "latin-1",
        "cp1252"
    ]

    for cod in codificaciones:
        try:
            return contenido.decode(cod)
        except:
            pass

    return contenido.decode("latin-1", errors="ignore")


def limpiar_numero(valor):

    if pd.isna(valor):
        return 0.0

    valor = str(valor).strip()

    if valor == "":
        return 0.0

    valor = valor.replace(".", "")
    valor = valor.replace(",", ".")

    try:
        return float(valor)
    except:
        return 0.0


def normalizar(texto):

    texto = str(texto).strip().lower()

    texto = texto.replace("á", "a")
    texto = texto.replace("é", "e")
    texto = texto.replace("í", "i")
    texto = texto.replace("ó", "o")
    texto = texto.replace("ú", "u")

    texto = re.sub(r"\s+", " ", texto)

    return texto


# =====================================================
# LECTOR CSV FLEXIBLE
# =====================================================

def leer_csv_flexible(archivo):

    texto = leer_texto_archivo(archivo)

    separadores = [
        ";",
        ",",
        "\t"
    ]

    for sep in separadores:

        try:

            df = pd.read_csv(
                StringIO(texto),
                sep=sep
            )

            if len(df.columns) > 1:
                return df

        except:
            pass

    raise Exception(
        "No se ha podido interpretar el CSV."
    )


# =====================================================
# IMPORTADOR BMS
# =====================================================

def transformar_csv_bms(archivo):

    df = leer_csv_flexible(archivo)

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    columnas = {
        normalizar(c): c
        for c in df.columns
    }

    posibles_tipologia = [
        "tipologia",
        "tipología",
        "categoria"
    ]

    posibles_elec = [
        "electricidad [kwh]",
        "electricidad",
        "electricity [kwh]"
    ]

    posibles_gas = [
        "gas natural [kwh]",
        "gas natural",
        "gas [kwh]"
    ]

    col_tipologia = None
    col_elec = None
    col_gas = None

    for p in posibles_tipologia:

        if normalizar(p) in columnas:
            col_tipologia = columnas[normalizar(p)]

    for p in posibles_elec:

        if normalizar(p) in columnas:
            col_elec = columnas[normalizar(p)]

    for p in posibles_gas:

        if normalizar(p) in columnas:
            col_gas = columnas[normalizar(p)]

    errores = []

    if col_tipologia is None:
        errores.append(
            f"No encuentro columna Tipologia. Detectadas: {list(df.columns)}"
        )

    if col_elec is None:
        errores.append(
            f"No encuentro columna Electricidad. Detectadas: {list(df.columns)}"
        )

    if col_gas is None:
        errores.append(
            f"No encuentro columna Gas Natural. Detectadas: {list(df.columns)}"
        )

    if errores:
        return None, errores

    datos = []

    for _, fila in df.iterrows():

        categoria = str(
            fila[col_tipologia]
        ).strip()

        if categoria == "":
            continue

        if normalizar(categoria) == "total mes":
            continue

        electricidad = limpiar_numero(
            fila[col_elec]
        )

        gas = limpiar_numero(
            fila[col_gas]
        )

        total = electricidad + gas

        datos.append({

            "categoria": categoria,

            "electricidad_kwh": electricidad,

            "gas_kwh": gas,

            "consumo_kwh": total,

            "nombre_original_bms": categoria

        })

    resultado = pd.DataFrame(datos)

    if resultado.empty:

        return None, [
            "No se encontraron datos válidos."
        ]

    return resultado, []


# =====================================================
# MAPEO BMS -> DESIGNBUILDER
# =====================================================

MAPEO_CATEGORIAS = {

    "Heating": "Heating",
    "Cooling": "Cooling",

    "Interior Lighting": "Interior Lighting",
    "Exterior Lighting": "Exterior Lighting",

    "Interior Equipment": "Interior Equipment",
    "Exterior Equipment": "Exterior Equipment",

    "Fans": "Fans",
    "Pumps": "Pumps",

    "Heat Rejection": "Heat Rejection",
    "Humidification": "Humidification",
    "Heat Recovery": "Heat Recovery",

    "Water Systems": "Water Systems",
    "Refrigeration": "Refrigeration",
    "Generators": "Generators"

}