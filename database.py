import sqlite3

DB = "database.db"

def crear_base_datos():

    conn = sqlite3.connect(DB)

    cursor = conn.cursor()

    cursor.execute("""
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

    conn.commit()
    conn.close()


if __name__ == "__main__":
    crear_base_datos()
    print("Base de datos creada correctamente")