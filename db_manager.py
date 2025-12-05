import os
import datetime
import json
from werkzeug.security import generate_password_hash, check_password_hash

# Librerías de PostgreSQL
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_ACTIVE = True
except ImportError:
    print("Advertencia: psycopg2 no está instalado. No se puede conectar a PostgreSQL.")
    POSTGRES_ACTIVE = False

# Librería para la función de reportes filtrados
try:
    import pandas as pd
except ImportError:
    print("Advertencia: pandas no está instalado. Las funciones de reportes filtrados pueden fallar.")
    pass

# --- AGREGAR ESTAS LÍNEAS PARA CARGAR VARIABLES LOCALES ---
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("Variables de .env cargadas localmente (si existe el archivo).")
except ImportError:
    pass
# -----------------------------------------------------------

DATABASE_URL = os.environ.get('DATABASE_URL')

# --- Funciones de Conexión ---
def get_db_connection():
    if not POSTGRES_ACTIVE:
        raise Exception("El módulo psycopg2 no está disponible o la importación falló.")
    
    if not DATABASE_URL: 
        raise ConnectionError("Falta la variable de entorno esencial DATABASE_URL. Revise su configuración.")

    try:
        # Usar la URI para conectar
        conn = psycopg2.connect(DATABASE_URL) 
        return conn
    except psycopg2.OperationalError as e:
        print(f"Error de conexión a PostgreSQL. Revise la variable DATABASE_URL: {e}")
        raise ConnectionError(f"No se pudo conectar a la base de datos: {e}")

def inicializar_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Tabla de Usuarios (Pilotos y Admins)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'piloto',
            is_active INTEGER NOT NULL DEFAULT 1
        );
    """)
    
    # 2. Tabla de Vehículos
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            plate TEXT PRIMARY KEY NOT NULL,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            year INTEGER,
            capacity_kg INTEGER,
            assigned_pilot_id INTEGER,
            FOREIGN KEY (assigned_pilot_id) REFERENCES users(id) ON DELETE SET NULL
        );
    """)
    
    # 3. TABLA CENTRAL DE REPORTES (MODIFICADA)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            vehicle_plate TEXT NOT NULL,
            report_date TIMESTAMP NOT NULL DEFAULT NOW(),
            km_actual REAL NOT NULL,
            km_proximo_servicio REAL,
            fecha_servicio_anterior DATE,
            observations TEXT,
            -- header_data ahora contiene los datos de promoción/licencia
            header_data JSONB NOT NULL,
            FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (vehicle_plate) REFERENCES vehicles(plate) ON DELETE CASCADE
        );
    """)
    
    # 4. CREACIÓN DEL TIPO ENUM para estandarizar estados
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_item') THEN
                CREATE TYPE estado_item AS ENUM ('Buen Estado', 'Mal Estado', 'N/A');
            END IF;
        END
        $$;
    """)
    
    # 5. TABLA DE DETALLES DE LA CHECKLIST (NUEVA TABLA RELACIONAL)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS detalles_inspeccion (
            id SERIAL PRIMARY KEY,
            report_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            item TEXT NOT NULL,
            estado estado_item NOT NULL,
            -- Si se desea una observacion por item, se podría añadir aquí
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE,
            UNIQUE (report_id, item)
        );
    """)
    
    # Crear usuario administrador si no existe
    cur.execute("SELECT id FROM users WHERE username = %s;", ('admin',))
    admin_exists = cur.fetchone()
    
    if not admin_exists:
        password_hash = generate_password_hash("admin123")
        cur.execute("""
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (username) DO NOTHING;
        """, ('admin', password_hash, 'Administrador Principal', 'admin'))
    
    conn.commit()
    conn.close()

# --- Funciones de la Aplicación (Modificadas) ---

# [Mantenemos todas las funciones intermedias (login, manage_user, get_all_pilots, etc.) sin cambios]
# ... (get_user_by_credentials, get_all_pilots, manage_user_web, get_all_vehicles, manage_vehicle, load_pilot_data)

def load_pilot_data(driver_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT 
            u.id, u.full_name, v.plate, v.brand, v.model 
        FROM users u
        LEFT JOIN vehicles v ON u.id = v.assigned_pilot_id
        WHERE u.id = %s;
    """, (driver_id,))
    
    data = cur.fetchone()
    conn.close()
    return data

def save_report_web(driver_id, header_data, checklist_results, observations, signature_confirmation):
    if signature_confirmation != 'confirmado':
        raise ValueError("Debe confirmar la inspección.")

    conn = get_db_connection()
    cur = conn.cursor()

    # Separación de datos
    vehicle_plate = header_data.pop('plate', None)
    km_actual = header_data.pop('km_actual', None)
    km_proximo_servicio = header_data.pop('km_proximo_servicio', None)
    fecha_servicio_anterior = header_data.pop('fecha_servicio_anterior', None)
    
    # Los datos restantes del encabezado (promoción, licencia, seguro) se guardan en JSONB
    header_json = json.dumps(header_data)

    if not vehicle_plate or km_actual is None:
        raise ValueError("Faltan datos críticos del vehículo o kilometraje.")
        
    try:
        # 1. INSERTAR REGISTRO PRINCIPAL EN REPORTS
        # Usamos RETURNING id para obtener el ID recién generado (clave)
        cur.execute("""
            INSERT INTO reports (
                driver_id, vehicle_plate, report_date, km_actual, observations, header_data,
                km_proximo_servicio, fecha_servicio_anterior
            ) VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            driver_id,
            vehicle_plate,
            km_actual,
            observations,
            header_json,
            km_proximo_servicio,
            fecha_servicio_anterior
        ))
        
        report_id = cur.fetchone()[0] # Obtenemos el ID del reporte insertado
        
        # 2. INSERTAR DETALLES DE LA CHECKLIST EN TABLA SEPARADA
        # Preparamos la lista de tuplas para la inserción masiva
        detalles_a_insertar = []
        for full_item_name, item_data in checklist_results.items():
            # item_data es un dict con 'categoria' y 'estado'
            detalles_a_insertar.append((
                report_id,
                item_data['categoria'],
                full_item_name, # El nombre del ítem completo
                item_data['estado']
            ))

        # Crear la sentencia INSERT INTO para inserción masiva
        if detalles_a_insertar:
            # Construcción dinámica de la sentencia (utilizando string formatting de SQL)
            insert_query = "INSERT INTO detalles_inspeccion (report_id, categoria, item, estado) VALUES (%s, %s, %s, %s)"
            psycopg2.extras.execute_batch(cur, insert_query, detalles_a_insertar)

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise Exception(f"Error al guardar el reporte: {e}")
    finally:
        conn.close()

def get_filtered_reports(start_date=None, end_date=None, pilot_id=None, plate=None):
    # Importante: pandas debe estar instalado para que esta función trabaje
    if 'pd' not in globals():
         raise ImportError("La librería pandas no está instalada, no se pueden usar reportes filtrados.")
         
    conn = get_db_connection()
    
    # 🌟 La consulta ahora se hace sobre reports y detalles_inspeccion (si fuera necesario)
    query = """
    SELECT
        r.id, r.report_date, u.full_name AS pilot_name, r.driver_id, r.vehicle_plate,
        r.km_actual, r.observations, r.header_data,
        -- Traer todos los detalles de la checklist para este reporte (como subconsulta o JOIN)
        (
            SELECT json_agg(row_to_json(di))
            FROM detalles_inspeccion di
            WHERE di.report_id = r.id
        ) AS checklist_details
    FROM reports r
    JOIN users u ON r.driver_id = u.id
    WHERE 1=1
    """
    params = {}
    
    # ... (Mantenemos la lógica de filtros) ...
    if start_date:
        query += " AND r.report_date >= %(start_date)s"
        params['start_date'] = start_date
    
    if end_date:
        query += " AND r.report_date <= %(end_date)s"
        params['end_date'] = end_date + " 23:59:59"
        
    if pilot_id:
        query += " AND r.driver_id = %(pilot_id)s"
        params['pilot_id'] = pilot_id
        
    if plate:
        query += " AND r.vehicle_plate = %(plate)s"
        params['plate'] = plate

    query += " ORDER BY r.report_date DESC"
    
    try:
        df = pd.read_sql_query(query, conn, params=params)
        
        # Deserialización JSONB: Asegurar que los datos JSON se conviertan a diccionarios
        if 'header_data' in df.columns:
            df['header_data'] = df['header_data'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
        
        reports_list = df.to_dict('records')
        return reports_list
        
    except Exception as e:
        raise Exception(f"Error al ejecutar consulta filtrada con pandas/psycopg2: {e}")
    finally:
        conn.close()


def delete_report(report_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # ON DELETE CASCADE se encargará de eliminar los detalles_inspeccion asociados
        cur.execute("DELETE FROM reports WHERE id = %s;", (report_id,))
        if cur.rowcount == 0:
            raise ValueError(f"No se encontró el reporte con ID {report_id} para eliminar.")
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise Exception(f"Error al eliminar el reporte: {e}")
    finally:
        conn.close()
