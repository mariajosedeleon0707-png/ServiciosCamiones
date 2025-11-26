# db_manager.py (Versión PostgreSQL / Supabase)

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
    # Esto ocurre si corres localmente sin instalar psycopg2-binary
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
    # Esto cargará el .env localmente, pero será ignorado en Vercel si ya existen las variables.
    load_dotenv()
    print("Variables de .env cargadas localmente (si existe el archivo).")
except ImportError:
    # Si la librería no está instalada, simplemente usa las variables del SO
    pass
# -----------------------------------------------------------


# --- CONFIGURACIÓN PARA POSTGRESQL (SUPABASE) ---
# Ahora estas líneas leerán primero del .env si existe, o de Vercel si estás desplegado
DB_HOST = os.environ.get('DB_HOST')
DB_NAME = os.environ.get('DB_NAME')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_PORT = os.environ.get('DB_PORT', '5432')


# --- Funciones de Conexión ---

def get_db_connection():
    if not POSTGRES_ACTIVE:
        raise Exception("El módulo psycopg2 no está disponible o la importación falló.")
    
    # **VALIDACIÓN CRÍTICA**
    if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        raise ConnectionError("Faltan variables de entorno esenciales (DB_HOST, DB_USER, DB_PASSWORD, etc.). Revise su archivo .env o la configuración de Vercel.")

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            # === ARREGLO CLAVE PARA VERCELL/SUPABASE ===
            # Fuerza la conexión a usar IPv4 para evitar el error 'Cannot assign requested address'
            fallback_application_name='Vercel_App_IPv4_Fix'
            # ==========================================
        )
        return conn
    except psycopg2.OperationalError as e:
        # Mensaje de error útil si fallan las variables de Vercel
        print(f"Error de conexión a PostgreSQL. Revise las Variables de Entorno de Vercel/Supabase: {e}")
        raise ConnectionError(f"No se pudo conectar a la base de datos: {e}")


def inicializar_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Tabla de Usuarios (Pilotos y Admins) - SINTAXIS POSTGRESQL
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
    
    # 2. Tabla de Vehículos - SINTAXIS POSTGRESQL
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
    
    # 3. Tabla de Reportes - SINTAXIS POSTGRESQL (usa JSONB)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            vehicle_plate TEXT NOT NULL,
            report_date TIMESTAMP NOT NULL,
            km_actual REAL NOT NULL,
            observations TEXT,
            header_data JSONB NOT NULL,
            checklist_data JSONB NOT NULL,
            FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (vehicle_plate) REFERENCES vehicles(plate) ON DELETE CASCADE
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

# --- Funciones de la Aplicación ---

def get_user_by_credentials(username, password):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM users WHERE username = %s;", (username,))
    user = cur.fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def get_all_pilots():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT 
            u.id, u.username, u.full_name, u.role, u.is_active,
            v.plate AS assigned_vehicle_plate
        FROM users u
        LEFT JOIN vehicles v ON v.assigned_pilot_id = u.id
        WHERE u.role = 'piloto'
        ORDER BY u.full_name;
    """)
    pilots = cur.fetchall()
    conn.close()
    return pilots

def manage_user_web(action, **kwargs):
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        if action == 'add':
            username = kwargs['username']
            full_name = kwargs['full_name']
            password = kwargs['password']
            
            cur.execute("SELECT id FROM users WHERE username = %s;", (username,))
            if cur.fetchone():
                raise ValueError(f"El nombre de usuario '{username}' ya está en uso.")
                
            password_hash = generate_password_hash(password)
            cur.execute("INSERT INTO users (username, password_hash, full_name) VALUES (%s, %s, %s);", 
                        (username, password_hash, full_name))
            
        elif action == 'delete':
            user_id = kwargs['user_id']
            # ON DELETE CASCADE maneja reportes. El FK en vehicles ya tiene ON DELETE SET NULL
            cur.execute("DELETE FROM users WHERE id = %s AND role = 'piloto';", (user_id,))
            
        elif action == 'toggle_status':
            user_id = kwargs['user_id']
            status = kwargs['status']
            new_status = 1 if int(status) == 0 else 0
            cur.execute("UPDATE users SET is_active = %s WHERE id = %s;", (new_status, user_id))
            
        conn.commit()
    except psycopg2.IntegrityError as e:
        conn.rollback()
        raise ValueError("Error: El nombre de usuario ya existe o error de integridad.")
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_all_vehicles():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT v.*, u.full_name AS assigned_pilot_name
        FROM vehicles v
        LEFT JOIN users u ON v.assigned_pilot_id = u.id
        ORDER BY v.plate;
    """)
    vehicles = cur.fetchall()
    conn.close()
    return vehicles

def manage_vehicle(action, **kwargs):
    conn = get_db_connection()
    cur = conn.cursor()
    plate = kwargs.get('plate')
    
    try:
        if action == 'add':
            plate = kwargs['plate']
            brand = kwargs['brand']
            model = kwargs['model']
            year = int(kwargs['year'])
            capacity_kg = int(kwargs['capacity_kg'])
            
            cur.execute("SELECT plate FROM vehicles WHERE plate = %s;", (plate,))
            if cur.fetchone():
                raise ValueError(f"La placa '{plate}' ya está registrada.")
                
            cur.execute("""
                INSERT INTO vehicles (plate, brand, model, year, capacity_kg) 
                VALUES (%s, %s, %s, %s, %s);
            """, (plate, brand, model, year, capacity_kg))
            
        elif action == 'update':
            brand = kwargs['brand']
            model = kwargs['model']
            year = int(kwargs['year'])
            capacity_kg = int(kwargs['capacity_kg'])
            
            cur.execute("""
                UPDATE vehicles 
                SET brand = %s, model = %s, year = %s, capacity_kg = %s 
                WHERE plate = %s;
            """, (brand, model, year, capacity_kg, plate))
            
        elif action == 'assign':
            pilot_id = kwargs['assign_pilot_id']
            # Desasigna la placa de cualquier otro piloto
            cur.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE assigned_pilot_id = %s;", (pilot_id,))
            # Asigna la placa al piloto actual
            cur.execute("UPDATE vehicles SET assigned_pilot_id = %s WHERE plate = %s;", (pilot_id, plate))
            
        elif action == 'unassign':
            cur.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE plate = %s;", (plate,))
            
        elif action == 'delete':
            cur.execute("DELETE FROM vehicles WHERE plate = %s;", (plate,))
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

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

    header_json = json.dumps(header_data)
    checklist_json = json.dumps(checklist_results)
    
    vehicle_plate = header_data.get('plate')
    km_actual = header_data.get('km_actual')

    if not vehicle_plate or km_actual is None:
        raise ValueError("Faltan datos críticos del vehículo o kilometraje.")
        
    try:
        # NOW() es la función de fecha/hora de PostgreSQL
        cur.execute("""
            INSERT INTO reports (
                driver_id, vehicle_plate, report_date, km_actual, observations, header_data, checklist_data
            ) VALUES (%s, %s, NOW(), %s, %s, %s, %s);
        """, (
            driver_id,
            vehicle_plate,
            km_actual,
            observations,
            header_json,
            checklist_json
        ))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise Exception(f"Error al guardar el reporte: {e}")
    finally:
        conn.close()

def get_filtered_reports(start_date=None, end_date=None, pilot_id=None, plate=None):
    # Usamos pandas.read_sql_query con la conexión a PostgreSQL (psycopg2)
    
    # Importante: pandas debe estar instalado para que esta función trabaje
    if 'pd' not in globals():
         raise ImportError("La librería pandas no está instalada, no se pueden usar reportes filtrados.")
         
    conn = get_db_connection()
    
    query = """
    SELECT
        r.id, r.report_date, u.full_name AS pilot_name, r.driver_id, r.vehicle_plate,
        r.km_actual, r.observations, r.header_data, r.checklist_data 
    FROM reports r
    JOIN users u ON r.driver_id = u.id
    WHERE 1=1
    """
    params = {}
    
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
        # (Esto puede ser necesario si la columna es leída como string por pandas/psycopg2)
        if 'header_data' in df.columns:
            df['header_data'] = df['header_data'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
        if 'checklist_data' in df.columns:
            df['checklist_data'] = df['checklist_data'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
        
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
        cur.execute("DELETE FROM reports WHERE id = %s;", (report_id,))
        if cur.rowcount == 0:
            raise ValueError(f"No se encontró el reporte con ID {report_id} para eliminar.")
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise Exception(f"Error al eliminar el reporte: {e}")
    finally:
        conn.close()
