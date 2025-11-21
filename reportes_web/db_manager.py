# db_manager.py

import sqlite3
import json
import datetime
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = "reportes_camiones.db"

# --- Funciones de Utilidad ---

def dict_factory(cursor, row):
    """Convierte filas de SQLite a diccionarios."""
    fields = [column[0] for column in cursor.description]
    return dict(zip(fields, row))

def inicializar_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Tabla de Usuarios (Pilotos y Admins)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            FOREIGN KEY (assigned_pilot_id) REFERENCES users(id)
        )
    """)
    
    # Tabla de Reportes
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            vehicle_plate TEXT NOT NULL,
            report_date TEXT NOT NULL,
            km_actual REAL NOT NULL,
            observations TEXT,
            header_data TEXT NOT NULL,      -- JSON
            checklist_data TEXT NOT NULL,   -- JSON
            FOREIGN KEY (driver_id) REFERENCES users(id),
            FOREIGN KEY (vehicle_plate) REFERENCES vehicles(plate)
        )
    """)
    
    # Insertar administrador por defecto si no existe
    try:
        c.execute("SELECT id FROM users WHERE username = 'admin'")
        if c.fetchone() is None:
            admin_password_hash = generate_password_hash("admin123")
            c.execute("""
                INSERT INTO users (username, password_hash, full_name, role) 
                VALUES (?, ?, ?, ?)
            """, ('admin', admin_password_hash, 'Administrador Principal', 'admin'))
    except sqlite3.IntegrityError:
        pass

    conn.commit()
    conn.close()

# --- Funciones de Autenticación y Carga de Datos ---

def get_user_by_credentials(username, password):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = dict_factory
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def get_all_pilots():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = dict_factory
    c = conn.cursor()
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
    users = c.fetchall()
    conn.close()
    return users

def get_all_vehicles():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = dict_factory
    c = conn.cursor()
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
    vehicles = c.fetchall()
    conn.close()
    return vehicles

def load_pilot_data(pilot_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = dict_factory
    c = conn.cursor()
    
    c.execute("""
        SELECT 
            u.id, 
            u.full_name, 
            v.plate, 
            v.brand, 
            v.model
        FROM users u
        LEFT JOIN vehicles v ON u.id = v.assigned_pilot_id
        WHERE u.id = ?
    """, (pilot_id,))
    
    data = c.fetchone()
    conn.close()
    return data

# --- Funciones de Gestión de Usuarios y Vehículos ---

def manage_user_web(action, user_id=None, full_name=None, username=None, password=None, status=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if action == 'add':
        if not all([full_name, username, password]):
            raise ValueError("Faltan datos para añadir usuario.")
        password_hash = generate_password_hash(password)
        try:
            c.execute("INSERT INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, 'piloto')", 
                      (full_name, username, password_hash))
        except sqlite3.IntegrityError:
            raise ValueError(f"El usuario '{username}' ya existe.")
    
    elif action == 'toggle_status' and user_id is not None and status is not None:
        new_status = 1 if status == '0' else 0
        c.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, user_id))
    
    elif action == 'delete' and user_id is not None:
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        c.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE assigned_pilot_id = ?", (user_id,))
    
    conn.commit()
    conn.close()

def manage_vehicle(action, plate, brand=None, model=None, year=None, capacity_kg=None, assign_pilot_id=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if action == 'add':
        if not all([plate, brand, model, year, capacity_kg]):
            raise ValueError("Faltan datos para añadir vehículo.")
        try:
            c.execute("INSERT INTO vehicles (plate, brand, model, year, capacity_kg) VALUES (?, ?, ?, ?, ?)",
                      (plate.upper(), brand, model, year, capacity_kg))
        except sqlite3.IntegrityError:
            raise ValueError(f"La placa '{plate}' ya existe.")
            
    elif action == 'update':
        if not all([plate, brand, model, year, capacity_kg]):
            raise ValueError("Faltan datos para actualizar vehículo.")
        c.execute("UPDATE vehicles SET brand=?, model=?, year=?, capacity_kg=? WHERE plate=?",
                  (brand, model, year, capacity_kg, plate.upper()))
        
    elif action == 'assign':
        if assign_pilot_id and assign_pilot_id != 'None':
            c.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE assigned_pilot_id = ?", (assign_pilot_id,))
            c.execute("UPDATE vehicles SET assigned_pilot_id = ? WHERE plate = ?", (assign_pilot_id, plate.upper()))
        else:
            c.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE plate = ?", (plate.upper(),))
    
    elif action == 'unassign':
        c.execute("UPDATE vehicles SET assigned_pilot_id = NULL WHERE plate = ?", (plate.upper(),))
    
    elif action == 'delete':
        c.execute("DELETE FROM reports WHERE vehicle_plate = ?", (plate.upper(),)) 
        c.execute("DELETE FROM vehicles WHERE plate = ?", (plate.upper(),))
        
    conn.commit()
    conn.close()

# --- Función de Guardar Reporte ---

def save_report_web(driver_id, report_data, checklist_results, observations, signature_confirmation):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    plate = report_data['plate']
    km_actual = report_data['km_actual']
    
    # El header_data almacena marca, modelo y la confirmación de firma
    header_data_json = json.dumps({
        'brand': report_data['brand'],
        'model': report_data['model'],
        'signature_confirmation': signature_confirmation 
    })
    
    checklist_json = json.dumps(checklist_results)
    report_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    c.execute("""
        INSERT INTO reports (driver_id, vehicle_plate, report_date, km_actual, observations, header_data, checklist_data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (driver_id, plate, report_date, km_actual, observations, header_data_json, checklist_json))
    
    conn.commit()
    conn.close()

def delete_report(report_id):
    """
    Elimina un reporte de inspección por su ID.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    
    
# --- Función de Reportes Filtrados (CRÍTICA) ---

def get_filtered_reports(start_date=None, end_date=None, pilot_id=None, plate=None):
    """
    Obtiene reportes aplicando filtros y asegura que las claves sean correctas.
    """
    conn = sqlite3.connect(DB_NAME)
    
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
        query += " AND r.report_date >= ?"
        params.append(start_date)
    
    if end_date:
        query += " AND r.report_date <= ?"
        params.append(end_date + " 23:59:59") 
        
    if pilot_id:
        query += " AND r.driver_id = ?"
        params.append(pilot_id)
        
    if plate:
        query += " AND r.vehicle_plate = ?"
        params.append(plate)

    query += " ORDER BY r.report_date DESC"
    
    try:
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        # Deserialización JSON: Convierte las strings JSON a objetos/diccionarios de Python
        df['header_data'] = df['header_data'].apply(lambda x: json.loads(x) if x else {})
        df['checklist_data'] = df['checklist_data'].apply(lambda x: json.loads(x) if x else {})
        
        return df.to_dict('records')
    except Exception as e:
        print(f"Error en get_filtered_reports: {e}")
        conn.close()
        return []