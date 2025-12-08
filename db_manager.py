# db_manager.py

import os
import datetime
import json
import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración y Dependencias ---
try:
    from dotenv import load_dotenv
    # Carga variables de .env localmente
    load_dotenv()
except ImportError:
    pass

try:
    import pandas as pd
except ImportError:
    pass

DATABASE_URL = os.environ.get('DATABASE_URL')
POSTGRES_ACTIVE = True

# --- Funciones de Conexión ---

def get_db_connection():
    """Establece la conexión a la base de datos PostgreSQL."""
    if not POSTGRES_ACTIVE:
        raise Exception("El módulo psycopg2 no está disponible.")
    
    if not DATABASE_URL: 
        raise ConnectionError("Falta la variable de entorno esencial DATABASE_URL. Revise su configuración.")

    try:
        conn = psycopg2.connect(DATABASE_URL) 
        return conn
    except psycopg2.OperationalError as e:
        print(f"Error de conexión a PostgreSQL. Revise la variable DATABASE_URL: {e}")
        raise ConnectionError(f"No se pudo conectar a la base de datos: {e}")

# --- Funciones de Inicialización (DDL y Migraciones) ---

def inicializar_db():
    """Crea todas las tablas necesarias si no existen y asegura el usuario 'admin'."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Tabla de Usuarios
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
    
    # 3. CREACIÓN DEL TIPO ENUM para estandarizar estados
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_item') THEN
                CREATE TYPE estado_item AS ENUM ('Buen Estado', 'Mal Estado', 'N/A');
            END IF;
        END
        $$;
    """)
    
    # 4. TABLA CENTRAL DE REPORTES (Estructura actual)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            driver_id INTEGER NOT NULL,
            vehicle_plate TEXT NOT NULL,
            report_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(), -- Cambiado a WITH TIME ZONE
            km_actual REAL NOT NULL,
            km_proximo_servicio REAL,
            fecha_servicio_anterior DATE,
            observations TEXT,
            header_data JSONB NOT NULL,
            FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (vehicle_plate) REFERENCES vehicles(plate) ON DELETE CASCADE
        );
    """)

    # 🌟 BLOQUE DE MIGRACIONES Y CORRECCIÓN DE ESQUEMA 🌟
    
    # 4.1. MIGRACIÓN: Añadir km_proximo_servicio (solución a "column does not exist")
    try:
        cur.execute("SELECT km_proximo_servicio FROM reports LIMIT 0;")
    except psycopg2.ProgrammingError:
        conn.rollback()
        cur.execute("ALTER TABLE reports ADD COLUMN km_proximo_servicio REAL;")
        print("MIGRACIÓN: Columna 'km_proximo_servicio' añadida a 'reports'.")
    
    # 4.2. MIGRACIÓN: Añadir fecha_servicio_anterior (solución a "column does not exist")
    try:
        cur.execute("SELECT fecha_servicio_anterior FROM reports LIMIT 0;")
    except psycopg2.ProgrammingError:
        conn.rollback()
        cur.execute("ALTER TABLE reports ADD COLUMN fecha_servicio_anterior DATE;")
        print("MIGRACIÓN: Columna 'fecha_servicio_anterior' añadida a 'reports'.")

    # 4.3. MIGRACIÓN CRÍTICA: Eliminar columna obsoleta checklist_data (solución a "violates not-null constraint")
    try:
        cur.execute("SELECT checklist_data FROM reports LIMIT 0;")
        conn.rollback() 
        cur.execute("ALTER TABLE reports DROP COLUMN checklist_data;")
        print("MIGRACIÓN: Columna obsoleta 'checklist_data' eliminada de 'reports'.")
    except psycopg2.ProgrammingError:
        conn.rollback()
        pass 
    # ----------------------------------------------------------------------
    
    # 5. TABLA DE DETALLES DE LA CHECKLIST (Relacional 1:N con reports)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS detalles_inspeccion (
            id SERIAL PRIMARY KEY,
            report_id INTEGER NOT NULL,
            categoria TEXT NOT NULL,
            item TEXT NOT NULL,
            estado estado_item NOT NULL,
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

# --- Funciones de Autenticación y Usuarios (CRUD) ---

def get_user_by_credentials(username, password):
    """Busca un usuario y verifica el hash de la contraseña."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM users WHERE username = %s;", (username,))
    user = cur.fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def get_all_pilots():
    """Obtiene la lista de todos los pilotos con su vehículo asignado."""
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
    """Gestiona usuarios (añadir, eliminar, cambiar estado)."""
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

# --- Funciones de Vehículos (CRUD) ---

def get_all_vehicles():
    """Obtiene la lista de todos los vehículos con el nombre del piloto asignado."""
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
    """Gestiona vehículos (añadir, actualizar, asignar/desasignar, eliminar)."""
    conn = get_db_connection()
    cur = conn.cursor()
    plate = kwargs.get('plate')
    
    try:
        if action == 'add':
            plate = kwargs['plate']
            cur.execute("""
                INSERT INTO vehicles (plate, brand, model, year, capacity_kg) 
                VALUES (%s, %s, %s, %s, %s);
            """, (plate, kwargs['brand'], kwargs['model'], int(kwargs['year']), int(kwargs['capacity_kg'])))
            
        elif action == 'update':
            cur.execute("""
                UPDATE vehicles 
                SET brand = %s, model = %s, year = %s, capacity_kg = %s 
                WHERE plate = %s;
            """, (kwargs['brand'], kwargs['model'], int(kwargs['year']), int(kwargs['capacity_kg']), plate))
            
        elif action == 'assign':
            pilot_id = kwargs['assign_pilot_id']
            cur.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE assigned_pilot_id = %s;", (pilot_id,))
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

# --- Funciones de Reportes (Inspección) ---

def load_pilot_data(driver_id):
    """Carga los datos del piloto y su vehículo asignado para mostrar en el formulario."""
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
    """
    Guarda el reporte de inspección.
    Realiza una inserción en reports y una inserción masiva en detalles_inspeccion.
    """
    if signature_confirmation != 'confirmado':
        raise ValueError("Debe confirmar la inspección para guardar el reporte.")

    conn = get_db_connection()
    cur = conn.cursor()

    # Extracción de datos para la tabla REPORTS
    vehicle_plate = header_data.pop('plate', None)
    km_actual = header_data.pop('km_actual', None)
    km_proximo_servicio = header_data.pop('km_proximo_servicio', None)
    fecha_servicio_anterior = header_data.pop('fecha_servicio_anterior', None)
    
    # El resto de header_data (licencia, promoción, etc.) se guarda en JSONB
    header_json = json.dumps(header_data)

    if not vehicle_plate or km_actual is None:
        raise ValueError("Faltan datos críticos: Placa o Kilometraje.")
        
    # Definir la zona horaria de Guatemala
    TIMEZONE_GUATEMALA = 'America/Guatemala'
    
    try:
        # 1. INSERTAR REGISTRO PRINCIPAL EN REPORTS y obtener el ID
        # Se utiliza (NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'America/Guatemala' para 
        # asegurar que la hora de guardado refleje la hora local de Guatemala.
        cur.execute("""
            INSERT INTO reports (
                driver_id, vehicle_plate, km_actual, observations, header_data,
                km_proximo_servicio, fecha_servicio_anterior, report_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, (NOW() AT TIME ZONE 'UTC') AT TIME ZONE %s)
            RETURNING id;
        """, (
            driver_id,
            vehicle_plate,
            km_actual,
            observations,
            header_json,
            km_proximo_servicio,
            fecha_servicio_anterior,
            TIMEZONE_GUATEMALA # Usa el nuevo parámetro de zona horaria
        ))
        
        report_id = cur.fetchone()[0]
        
        # 2. PREPARAR E INSERTAR DETALLES DE LA CHECKLIST (Inserción Masiva)
        detalles_a_insertar = []
        for full_item_name, item_data in checklist_results.items():
            detalles_a_insertar.append((
                report_id,
                item_data['categoria'],
                full_item_name,
                item_data['estado']
            ))

        if detalles_a_insertar:
            insert_query = "INSERT INTO detalles_inspeccion (report_id, categoria, item, estado) VALUES (%s, %s, %s, %s)"
            execute_batch(cur, insert_query, detalles_a_insertar)

        conn.commit()
    except Exception as e:
        conn.rollback()
        # Se lanza la excepción para que Flask la capture y muestre el error
        raise Exception(f"Error al guardar el reporte: {e}") 
    finally:
        conn.close()


def get_filtered_reports(start_date=None, end_date=None, pilot_id=None, plate=None):
    """Recupera reportes filtrados, usando pandas para la gestión de datos complejos."""
    if 'pd' not in globals():
        raise ImportError("La librería pandas no está instalada, no se pueden usar reportes filtrados.")
        
    conn = get_db_connection()
    
    # Consulta principal: Une reports con users y subconsulta los detalles de la checklist.
    query = """
    SELECT
        r.id, r.report_date, u.full_name AS pilot_name, r.driver_id, r.vehicle_plate,
        r.km_actual, r.observations, r.header_data, r.km_proximo_servicio, r.fecha_servicio_anterior,
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
    
    # Lógica de filtros
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
        
        # Deserialización JSONB
        if 'header_data' in df.columns:
            # pd.read_sql_query devuelve strings para JSONB, necesitan deserialización
            df['header_data'] = df['header_data'].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
        
        reports_list = df.to_dict('records')
        return reports_list
        
    except Exception as e:
        raise Exception(f"Error al ejecutar consulta filtrada con pandas/psycopg2: {e}")
    finally:
        conn.close()


def delete_report(report_id):
    """Elimina un reporte y sus detalles asociados (gracias a ON DELETE CASCADE)."""
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
