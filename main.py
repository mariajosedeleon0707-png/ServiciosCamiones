import os
from datetime import datetime, timedelta 
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from functools import wraps
from werkzeug.exceptions import HTTPException
import pandas as pd
import csv
from io import StringIO

# Importar configuración y DB Manager
import config
import db_manager as db

# --- Configuración de Flask ---
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1) 

# Lista de estados válidos normalizados para la validación
ESTADOS_VALIDOS_NORMALIZADOS = ["Buen Estado", "Mal Estado", "N/A"]

# --- Decoradores y Manejo de Sesión (CORREGIDO) ---

def login_required(f):
    """Decorador para restringir el acceso a usuarios no logueados."""
    @wraps(f)
    # CORRECCIÓN CLAVE: decorated_function DEBE aceptar *args y **kwargs
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    # CORRECCIÓN CLAVE: El decorador retorna la función envuelta
    return decorated_function
    
def role_required(role):
    """Decorador para restringir el acceso por rol (solo 'admin')."""
    def wrapper(f):
        @wraps(f)
        # CORRECCIÓN CLAVE: decorated_function DEBE aceptar *args y **kwargs
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] != role:
                flash('Acceso denegado: Se requiere rol de Administrador.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        # CORRECCIÓN CLAVE: El wrapper retorna la función envuelta
        return decorated_function
    return wrapper

# --- Rutas de Autenticación y Dashboard ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Maneja el inicio de sesión."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = db.get_user_by_credentials(username, password)
        
        if user and user['is_active']:
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            flash(f'¡Bienvenido, {user["full_name"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas o usuario inactivo.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Cierra la sesión del usuario."""
    session.clear()
    flash('Sesión cerrada exitosamente.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    """Ruta principal (endpoint 'dashboard'). CORRIGE el error 'home' en templates."""
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif session.get('role') == 'piloto':
        return redirect(url_for('pilot_form'))
    return redirect(url_for('logout'))

# --- Lógica de Pilotos (Formulario de Inspección) ---

def normalize_item_name(item_name):
    """Normaliza el nombre del ítem para crear la clave consistente para la BD."""
    return item_name.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace(',', '').replace('-', '').replace('.', '')

def validate_and_parse_checklist(form_data):
    """Valida que todos los ítems de la checklist hayan sido marcados y los estructura."""
    checklist_results = {}
    
    item_map = {}
    all_expected_keys = []
    for category, items in config.CHECKLIST_ITEMS:
        for item in items:
            normalized_name = normalize_item_name(item)
            item_map[normalized_name] = (item, category)
            all_expected_keys.extend([f'check_{normalized_name}'])
            
    for expected_key in all_expected_keys:
        state = form_data.get(expected_key)
        
        if not state:
            raise ValueError(f"Falta el estado de un ítem requerido: {expected_key}")
        
        if state not in ESTADOS_VALIDOS_NORMALIZADOS:
            raise ValueError(f"Estado inválido para {expected_key}: {state}")

        normalized_name = expected_key.replace('check_', '')
        full_item_name, category = item_map.get(normalized_name)
        
        checklist_results[full_item_name] = {
            'categoria': category,
            'estado': state
        }
        
    return checklist_results

@app.route('/pilot_form', methods=['GET', 'POST'])
@login_required
def pilot_form():
    """Muestra el formulario de inspección y maneja su envío."""
    driver_id = session.get('user_id')
    
    try:
        pilot_data = db.load_pilot_data(driver_id)
    except Exception as e:
        flash(f"Error al cargar datos de piloto/vehículo: {e}", 'danger')
        pilot_data = None
        
    if not pilot_data or not pilot_data.get('plate'):
        flash('No tienes un vehículo asignado. No puedes realizar la inspección.', 'warning')
        return render_template('pilot_form.html', pilot_data=None, error="No hay vehículo asignado.")

    if request.method == 'POST':
        try:
            checklist_results = validate_and_parse_checklist(request.form)
            
            header_data = {
                'plate': pilot_data['plate'],
                'km_actual': float(request.form['km_actual']),
                'km_proximo_servicio': float(request.form.get('km_proximo_servicio')) if request.form.get('km_proximo_servicio') else None,
                'fecha_servicio_anterior': request.form.get('fecha_servicio_anterior') if request.form.get('fecha_servicio_anterior') else None,
                'promo_marca': request.form['promo_marca'],
                'fecha_inicio': request.form['fecha_inicio'],
                'fecha_finalizacion': request.form['fecha_finalizacion'],
                'tipo_licencia': request.form['tipo_licencia'],
                'vencimiento_licencia': request.form['vencimiento_licencia'],
                'tarjeta_seguro': request.form['tarjeta_seguro'],
            }
            
            observations = request.form.get('observations')
            signature_confirmation = request.form.get('signature_confirmation')
            
            db.save_report_web(
                driver_id=driver_id,
                header_data=header_data,
                checklist_results=checklist_results,
                observations=observations,
                signature_confirmation=signature_confirmation
            )
            
            flash('✅ Reporte de Inspección guardado con éxito.', 'success')
            return redirect(url_for('pilot_form'))
            
        except ValueError as e:
            flash(f'Error de validación: {e}', 'danger')
        except Exception as e:
            flash(f'Error al guardar el reporte: {e}', 'danger')

    return render_template('pilot_form.html', pilot_data=pilot_data, checklist=config.CHECKLIST_ITEMS)

# --- Rutas de Administrador ---

@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    """Panel principal de administración. Usa admin_base.html como dashboard (ajustado a tu estructura)."""
    return render_template('admin_base.html') 

# --- Gestión de Usuarios ---

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_users():
    """Gestión de pilotos. Usa admin_pilots.html (ajustado a tu estructura)."""
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')
        
        try:
            if action == 'add':
                db.manage_user_web(
                    action='add',
                    username=request.form['username'],
                    full_name=request.form['full_name'],
                    password=request.form['password']
                )
                flash('Piloto agregado exitosamente.', 'success')
            
            elif action == 'delete' and user_id:
                db.manage_user_web(action='delete', user_id=int(user_id))
                flash('Piloto eliminado exitosamente.', 'success')
                
            elif action == 'toggle_status' and user_id:
                status = request.form.get('current_status')
                db.manage_user_web(action='toggle_status', user_id=int(user_id), status=status)
                flash('Estado del piloto actualizado.', 'success')
                
            else:
                flash('Acción o parámetros inválidos.', 'warning')
                
        except ValueError as e:
            flash(f'Error: {e}', 'danger')
        except Exception as e:
            flash(f'Error al procesar la solicitud: {e}', 'danger')
            
        return redirect(url_for('manage_users'))

    pilots = db.get_all_pilots()
    return render_template('admin_pilots.html', pilots=pilots)

# --- Gestión de Vehículos ---

@app.route('/admin/vehicles', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_vehicles():
    """Gestión y asignación de vehículos. Usa admin_vehicles.html (ajustado a tu estructura)."""
    if request.method == 'POST':
        action = request.form.get('action')
        plate = request.form.get('plate')
        
        try:
            if action == 'add' or action == 'update':
                kwargs = {
                    'plate': request.form['plate'],
                    'brand': request.form['brand'],
                    'model': request.form['model'],
                    'year': request.form['year'],
                    'capacity_kg': request.form['capacity_kg']
                }
                db.manage_vehicle(action=action, **kwargs)
                flash(f'Vehículo {action}izado exitosamente.', 'success')
            
            elif action == 'delete' and plate:
                db.manage_vehicle(action='delete', plate=plate)
                flash('Vehículo eliminado exitosamente.', 'success')
            
            elif action == 'assign' and plate:
                pilot_id = request.form.get('assign_pilot_id')
                if not pilot_id or pilot_id == 'none':
                     db.manage_vehicle(action='unassign', plate=plate)
                     flash('Vehículo desasignado exitosamente.', 'success')
                else:
                    db.manage_vehicle(action='assign', plate=plate, assign_pilot_id=int(pilot_id))
                    flash('Vehículo asignado exitosamente.', 'success')

            else:
                flash('Acción o parámetros inválidos.', 'warning')
                
        except Exception as e:
            flash(f'Error al procesar la solicitud: {e}', 'danger')
            
        return redirect(url_for('manage_vehicles'))

    vehicles = db.get_all_vehicles()
    pilots = db.get_all_pilots()
    return render_template('admin_vehicles.html', vehicles=vehicles, pilots=pilots)

# --- Rutas de Reportes ---

@app.route('/admin/reports', methods=['GET'])
@login_required
@role_required('admin')
def view_reports():
    """Muestra la lista de reportes de inspección con filtros. Usa admin_reports.html."""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id = request.args.get('pilot_id')
    plate = request.args.get('plate')
    
    try:
        reports = db.get_filtered_reports(start_date, end_date, pilot_id, plate)
        
        for report in reports:
            if report.get('report_date'):
                if isinstance(report['report_date'], datetime):
                    report['report_date_str'] = report['report_date'].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    try:
                        report_dt = datetime.fromisoformat(str(report['report_date']))
                        report['report_date_str'] = report_dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        report['report_date_str'] = str(report['report_date'])

    except ImportError:
        reports = []
        flash('Error: La librería Pandas no está instalada, no se pueden ver los reportes.', 'danger')
    except Exception as e:
        reports = []
        flash(f'Error al cargar los reportes: {e}', 'danger')

    all_pilots = db.get_all_pilots()
    all_vehicles = db.get_all_vehicles()
    
    return render_template('admin_reports.html', 
                           reports=reports, 
                           pilots=all_pilots, 
                           vehicles=all_vehicles,
                           current_filters={
                               'start_date': start_date,
                               'end_date': end_date,
                               'pilot_id': pilot_id,
                               'plate': plate
                           })

@app.route('/admin/reports/delete/<int:report_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_report(report_id):
    """Elimina un reporte específico."""
    try:
        db.delete_report(report_id)
        flash(f'Reporte ID {report_id} eliminado exitosamente.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        flash(f'Error al eliminar el reporte: {e}', 'danger')
    
    return redirect(url_for('view_reports'))


@app.route('/admin/reports/export_csv', methods=['GET'])
@login_required
@role_required('admin')
def export_csv():
    """Genera y descarga un CSV con los reportes filtrados."""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id = request.args.get('pilot_id')
    plate = request.args.get('plate')
    
    try:
        reports = db.get_filtered_reports(start_date, end_date, pilot_id, plate)
        
        if not reports:
            flash('No hay datos para exportar con los filtros seleccionados.', 'info')
            return redirect(url_for('view_reports', **request.args))
            
        static_headers = [
            'ID Reporte', 'Fecha Reporte (Guatemala)', 'Piloto', 'Placa', 
            'KM Actual', 'KM Próximo Servicio', 'Fecha Servicio Anterior', 
            'Marca Promoción', 'Fecha Inicio Promoción', 'Fecha Fin Promoción',
            'Tipo Licencia', 'Vencimiento Licencia', 'Tarjeta Seguro', 'Observaciones'
        ]
        
        checklist_headers = []
        for _, items in config.CHECKLIST_ITEMS:
            checklist_headers.extend(items)
        
        all_headers = static_headers + checklist_headers
        
        def generate():
            csv_buffer = StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=all_headers)
            writer.writeheader()

            for report in reports:
                row = {}
                row['ID Reporte'] = report.get('id', '')
                
                report_date = report.get('report_date')
                if isinstance(report_date, datetime):
                    row['Fecha Reporte (Guatemala)'] = report_date.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    row['Fecha Reporte (Guatemala)'] = str(report_date or '')

                row['Piloto'] = report.get('pilot_name', '')
                row['Placa'] = report.get('vehicle_plate', '')
                row['KM Actual'] = report.get('km_actual', '')
                row['KM Próximo Servicio'] = report.get('km_proximo_servicio', '')
                
                fecha_servicio_anterior = report.get('fecha_servicio_anterior')
                if isinstance(fecha_servicio_anterior, datetime):
                    row['Fecha Servicio Anterior'] = fecha_servicio_anterior.strftime('%Y-%m-%d')
                else:
                    row['Fecha Servicio Anterior'] = str(fecha_servicio_anterior or '')
                
                row['Observaciones'] = report.get('observations', '')
                
                header_data = report.get('header_data', {})
                row['Marca Promoción'] = header_data.get('promo_marca', '')
                row['Fecha Inicio Promoción'] = header_data.get('fecha_inicio', '')
                row['Fecha Fin Promoción'] = header_data.get('fecha_finalizacion', '')
                row['Tipo Licencia'] = header_data.get('tipo_licencia', '')
                row['Vencimiento Licencia'] = header_data.get('vencimiento_licencia', '')
                row['Tarjeta Seguro'] = header_data.get('tarjeta_seguro', '')
                
                checklist_map = {item['item']: item['estado'] for item in report.get('checklist_details', [])}
                
                for item_name in checklist_headers:
                    row[item_name] = checklist_map.get(item_name, 'No Registrado')
                    
                writer.writerow(row)
                
                yield csv_buffer.getvalue()
                csv_buffer.seek(0)
                csv_buffer.truncate(0)

            
        now = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"reporte_inspeccion_{now}.csv"
        
        response = Response(generate(), mimetype='text/csv')
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response

    except Exception as e:
        flash(f'Error al generar el archivo CSV: {e}', 'danger')
        return redirect(url_for('view_reports'))

# --- Manejo de errores ---

@app.errorhandler(404)
def page_not_found(e):
    # CORREGIDO: Llama a 404.html
    return render_template('404.html'), 404

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    
    app.logger.error(f"Error inesperado: {e}")
    # CORREGIDO: Llama a 500.html
    return render_template('500.html', error=str(e)), 500

# --- Inicialización y Ejecución ---

if __name__ == '__main__':
    try:
        db.inicializar_db()
        print("Base de datos inicializada/verificada.")
    except ConnectionError as e:
        print(f"Error CRÍTICO al conectar/inicializar la DB: {e}")
    except Exception as e:
        print(f"Error desconocido durante la inicialización de la DB: {e}")
        
    app.run(debug=True)
