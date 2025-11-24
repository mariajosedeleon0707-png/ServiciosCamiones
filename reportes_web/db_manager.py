# db_manager.py (VERSION ARREGLADA PARA SUPABASE/POSTGRESQL)

import os
import json
import datetime
import pandas as pd
import psycopg2
import psycopg2.extras
from psycopg2 import sql
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuración de Conexión ---

def get_db_connection():
    """
    Crea y devuelve un objeto de conexión a PostgreSQL.
    Lee las credenciales de las variables de entorno de Vercel.
    """
    # ⚠️ Las variables de entorno DEBEN estar configuradas en Vercel (ver instrucciones abajo)
    return psycopg2.connect(
        host=os.environ.get('DB_HOST'),
        database=os.environ.get('DB_NAME', 'postgres'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD'),
        port=os.environ.get('DB_PORT', '5432')
    )

# --- Funciones de Inicialización ---

def inicializar_db():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as c:
            
            # Tabla de Usuarios (SERIAL PRIMARY KEY y TEXT)
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'piloto',
                    is_active INTEGER NOT NULL DEFAULT 1
                )
            """)
            
            # Tabla de Vehículos
            c.execute("""
                CREATE TABLE IF NOT EXISTS vehicles (
                    plate TEXT PRIMARY KEY NOT NULL,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    year INTEGER,
                    capacity_kg INTEGER,
                    assigned_pilot_id INTEGER,
                    FOREIGN KEY (assigned_pilot_id) REFERENCES users(id) ON DELETE SET NULL
                )
            """)
            
            # Tabla de Reportes (SERIAL, TIMESTAMP y JSONB para rendimiento)
            c.execute("""
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
                )
            """)
            
            # Insertar administrador por defecto si no existe (usando %s)
            admin_username = 'admin'
            c.execute("SELECT id FROM users WHERE username = %s", (admin_username,))
            if c.fetchone() is None:
                admin_password_hash = generate_password_hash("admin123")
                c.execute("""
                    INSERT INTO users (username, password_hash, full_name, role) 
                    VALUES (%s, %s, %s, %s)
                """, (admin_username, admin_password_hash, 'Administrador Principal', 'admin'))

        conn.commit()
    except psycopg2.Error as e:
        print(f"Error al inicializar la base de datos: {e}")
    finally:
        if conn:
            conn.close()

# --- Funciones de Autenticación y Carga de Datos ---

def get_user_by_credentials(username, password):
    conn = None
    user = None
    try:
        conn = get_db_connection()
        # Usamos DictCursor para obtener resultados como diccionarios
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c: 
            c.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = c.fetchone()
            
            if user and check_password_hash(user['password_hash'], password):
                # Convertimos el DictRow a un diccionario estándar
                return dict(user)
    except psycopg2.Error as e:
        print(f"Error en get_user_by_credentials: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_all_pilots():
    conn = None
    users = []
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("""
                SELECT 
                    u.id, 
                    u.full_name, 
                    u.username, 
                    u.role, 
                    u.is_active, 
                    v.plate AS assigned_vehicle_plate
                FROM users u
                LEFT JOIN vehicles v ON u.id = v.assigned_pilot_id
                WHERE u.role = 'piloto'
                ORDER BY u.full_name
            """)
            users = [dict(row) for row in c.fetchall()]
    except psycopg2.Error as e:
        print(f"Error en get_all_pilots: {e}")
    finally:
        if conn:
            conn.close()
    return users

def get_all_vehicles():
    conn = None
    vehicles = []
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("""
                SELECT 
                    v.plate, 
                    v.brand, 
                    v.model, 
                    v.year, 
                    v.capacity_kg, 
                    v.assigned_pilot_id,
                    u.full_name AS assigned_pilot_name
                FROM vehicles v
                LEFT JOIN users u ON v.assigned_pilot_id = u.id
                ORDER BY v.plate
            """)
            vehicles = [dict(row) for row in c.fetchall()]
    except psycopg2.Error as e:
        print(f"Error en get_all_vehicles: {e}")
    finally:
        if conn:
            conn.close()
    return vehicles

def load_pilot_data(pilot_id):
    conn = None
    data = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute("""
                SELECT 
                    u.id, 
                    u.full_name, 
                    v.plate, 
                    v.brand, 
                    v.model
                FROM users u
                LEFT JOIN vehicles v ON u.id = v.assigned_pilot_id
                WHERE u.id = %s
            """, (pilot_id,))
            data = c.fetchone()
            if data:
                return dict(data)
    except psycopg2.Error as e:
        print(f"Error en load_pilot_data: {e}")
    finally:
        if conn:
            conn.close()
    return None

# --- Funciones de Gestión de Usuarios y Vehículos ---

def manage_user_web(action, user_id=None, full_name=None, username=None, password=None, status=None):
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        if action == 'add':
            if not all([full_name, username, password]):
                raise ValueError("Faltan datos para añadir usuario.")
            password_hash = generate_password_hash(password)
            try:
                c.execute("INSERT INTO users (full_name, username, password_hash, role) VALUES (%s, %s, %s, 'piloto')", 
                          (full_name, username, password_hash))
            except psycopg2.IntegrityError:
                raise ValueError(f"El usuario '{username}' ya existe.")
        
        elif action == 'toggle_status' and user_id is not None and status is not None:
            new_status = 1 if status == '0' else 0
            c.execute("UPDATE users SET is_active = %s WHERE id = %s", (new_status, user_id))
        
        elif action == 'delete' and user_id is not None:
            c.execute("DELETE FROM users WHERE id = %s", (user_id,))
            # La tabla vehicles tiene ON DELETE SET NULL
            
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Error de base de datos al gestionar usuario: {e}")
    finally:
        if conn:
            conn.close()

def manage_vehicle(action, plate, brand=None, model=None, year=None, capacity_kg=None, assign_pilot_id=None):
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        if action == 'add':
            if not all([plate, brand, model, year, capacity_kg]):
                raise ValueError("Faltan datos para añadir vehículo.")
            try:
                c.execute("INSERT INTO vehicles (plate, brand, model, year, capacity_kg) VALUES (%s, %s, %s, %s, %s)",
                          (plate.upper(), brand, model, year, capacity_kg))
            except psycopg2.IntegrityError:
                raise ValueError(f"La placa '{plate}' ya existe.")
                
        elif action == 'update':
            if not all([plate, brand, model, year, capacity_kg]):
                raise ValueError("Faltan datos para actualizar vehículo.")
            c.execute("UPDATE vehicles SET brand=%s, model=%s, year=%s, capacity_kg=%s WHERE plate=%s",
                      (brand, model, year, capacity_kg, plate.upper()))
            
        elif action == 'assign':
            if assign_pilot_id and assign_pilot_id != 'None':
                # Primero desasigna el piloto de cualquier otro vehículo
                c.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE assigned_pilot_id = %s", (assign_pilot_id,))
                # Luego asigna al nuevo vehículo
                c.execute("UPDATE vehicles SET assigned_pilot_id = %s WHERE plate = %s", (assign_pilot_id, plate.upper()))
            else:
                c.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE plate = %s", (plate.upper(),))
        
        elif action == 'unassign':
            c.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE plate = %s", (plate.upper(),))
        
        elif action == 'delete':
            # La tabla reports tiene ON DELETE CASCADE, pero es más seguro eliminar explícitamente si no se confía 100% en la FK
            c.execute("DELETE FROM reports WHERE vehicle_plate = %s", (plate.upper(),)) 
            c.execute("DELETE FROM vehicles WHERE plate = %s", (plate.upper(),))
            
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Error de base de datos al gestionar vehículo: {e}")
    finally:
        if conn:
            conn.close()

# --- Función de Guardar Reporte ---

def save_report_web(driver_id, report_data, checklist_results, observations, signature_confirmation):
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        plate = report_data['plate']
        km_actual = report_data['km_actual']
        
        header_data_json = json.dumps({
            'brand': report_data['brand'],
            'model': report_data['model'],
            'signature_confirmation': signature_confirmation
        })
        
        checklist_json = json.dumps(checklist_results)
        # Usamos TIMESTAMP de PostgreSQL.
        report_date = datetime.datetime.now()

        # Usamos JSONB para guardar los datos JSON
        c.execute("""
            INSERT INTO reports (driver_id, vehicle_plate, report_date, km_actual, observations, header_data, checklist_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (driver_id, plate, report_date, km_actual, observations, header_data_json, checklist_json))
        
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Error de base de datos al guardar reporte: {e}")
    finally:
        if conn:
            conn.close()

def delete_report(report_id):
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM reports WHERE id = %s", (report_id,))
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise Exception(f"Error de base de datos al eliminar reporte: {e}")
    finally:
        if conn:
            conn.close()
        
# --- Función de Reportes Filtrados (CRÍTICA) ---

def get_filtered_reports(start_date=None, end_date=None, pilot_id=None, plate=None):
    """
    Obtiene reportes aplicando filtros, usando pandas con conexión PostgreSQL.
    """
    conn = None
    query = """
    SELECT
        r.id,
        r.report_date,
        u.full_name AS pilot_name, 
        r.driver_id,
        r.vehicle_plate,
        r.km_actual,
        r.observations,
        r.header_data,  
        r.checklist_data 
    FROM 
        reports r
    JOIN 
        users u ON r.driver_id = u.id
    WHERE 1=1
    """
    params = []
    
    if start_date:
        query += " AND r.report_date >= %s"
        params.append(start_date)
    
    if end_date:
        query += " AND r.report_date <= %s"
        # Incluye hasta el final del día
        params.append(end_date + " 23:59:59") 
        
    if pilot_id:
        query += " AND r.driver_id = %s"
        params.append(pilot_id)
        
    if plate:
        query += " AND r.vehicle_plate = %s"
        params.append(plate)

    query += " ORDER BY r.report_date DESC"
    
    try:
        conn = get_db_connection()
        # pandas.read_sql_query es compatible con la conexión de psycopg2 y maneja los parámetros %s
        df = pd.read_sql_query(query, conn, params=params)
        
        # Deserialización JSON: Convierte las strings JSON a objetos/diccionarios de Python
        # JSONB en PostgreSQL ya es casi un objeto de Python, pero pandas lo lee como string,
        # así que la deserialización sigue siendo necesaria para asegurar el tipo de dato.
        df['header_data'] = df['header_data'].apply(lambda x: json.loads(x) if x and isinstance(x, str) else x)
        df['checklist_data'] = df['checklist_data'].apply(lambda x: json.loads(x) if x and isinstance(x, str) else x)
        
        return df.to_dict('records')
    except Exception as e:
        print(f"Error en get_filtered_reports: {e}")
        return []
    finally:
        if conn:
            conn.close()
