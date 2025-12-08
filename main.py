import csv
import json
import io
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
from functools import wraps
from datetime import datetime, timedelta

# Importaciones de módulos locales (config y db_manager)
from config import SECRET_KEY, CHECKLIST_ITEMS
import db_manager

# --- Inicialización y Configuración de Flask ---
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1) 

# --- CONSTANTE DE ESTADOS VÁLIDOS ---
ESTADOS_VALIDOS = ["Buen Estado", "Mal Estado", "N/A"]
ESTADOS_VALIDOS_NORMALIZADOS = [s.lower().strip() for s in ESTADOS_VALIDOS]
# ------------------------------------

# --- Decoradores ---

def login_required(f):
    """Decorador para restringir el acceso a usuarios no logueados."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorador para restringir el acceso solo a usuarios con rol 'admin'."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # NOTA: Si el rol de admin en tu DB es 'a', debes cambiar 'admin' por 'a' aquí.
        if session.get('role') not in ('admin', 'a'): 
            flash('Acceso denegado: Se requiere rol de Administrador.', 'danger')
            return redirect(url_for('pilot_form')) 
        return f(*args, **kwargs)
    return decorated_function

# 🛠️ --- Filtros Personalizados de Jinja ---

def format_thousand_separator(value):
    """Formatea un número con separadores de miles usando punto."""
    try:
        formatted = f"{int(value):,}"
        return formatted.replace(',', '.')
    except (ValueError, TypeError):
        return str(value)

app.jinja_env.filters['separator'] = format_thousand_separator

# 🛠️ --- Rutas de Autenticación y Home (Dashboard) ---

@app.route('/')
@login_required
def home(): 
    """Ruta principal, redirige según el rol."""
    # NOTA: Si el rol de admin es 'a' y piloto es 'p', debe reflejarse aquí.
    user_role = session.get('role', '').lower()
    
    if user_role in ('admin', 'a'):
        return redirect(url_for('admin_reports'))
    elif user_role in ('piloto', 'p'):
        return redirect(url_for('pilot_form'))
    return redirect(url_for('logout'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = db_manager.get_user_by_credentials(username, password)

        if user and user.get('is_active') == 1:
            session['user_id'] = user.get('id')
            session['username'] = user.get('username')
            session['full_name'] = user.get('full_name')
            session['role'] = user.get('role') # Guarda el rol tal como está en la DB ('p' o 'admin')
            flash(f'Bienvenido, {user.get("full_name")}!', 'success')
            return redirect(url_for('home'))
        elif user and user.get('is_active') == 0:
            flash("Su cuenta ha sido deshabilitada. Contacte al administrador.", 'danger')
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada exitosamente.', 'info')
    return redirect(url_for('login'))

# --- RUTA DE PILOTOS (FORMULARIO) ---

@app.route('/pilot_form', methods=['GET', 'POST'])
@login_required
def pilot_form():
    user_role = session.get('role', '').lower()
    if user_role not in ('piloto', 'p'):
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('home'))

    pilot_data = db_manager.load_pilot_data(session['user_id'])

    if not pilot_data or not pilot_data.get('plate'):
        return render_template('pilot_form.html', error="No tiene un vehículo asignado. Contacte a su administrador.", pilot_data=None)

    if request.method == 'POST':
        try:
            # 1. VALIDACIÓN Y RECOLECCIÓN DE DATOS GENERALES
            
            km_actual_str = request.form.get('km_actual')
            if not km_actual_str:
                raise ValueError("El campo Kilometraje Actual es obligatorio.")
            try:
                km_actual = float(km_actual_str)
            except ValueError:
                raise ValueError("El Kilometraje Actual debe ser un número válido.")
            
            observations = request.form.get('observations', '')
            
            signature_confirmation = request.form.get('signature_confirmation')
            if signature_confirmation is None:
                raise ValueError("Debe confirmar con la firma (checkbox) para enviar el reporte.")
            
            # Recoger los demás campos
            promo_marca = request.form.get('promo_marca', '')
            fecha_inicio = request.form.get('fecha_inicio', '')
            fecha_finalizacion = request.form.get('fecha_finalizacion', '')
            tipo_licencia = request.form.get('tipo_licencia', '')
            vencimiento_licencia = request.form.get('vencimiento_licencia', '')
            tarjeta_seguro = request.form.get('tarjeta_seguro', '')
            km_proximo_servicio = request.form.get('km_proximo_servicio')
            fecha_servicio_anterior = request.form.get('fecha_servicio_anterior')

            # 2. Estructurar el header_data
            report_data = {
                'plate': pilot_data['plate'],
                'km_actual': km_actual,
                'km_proximo_servicio': km_proximo_servicio,
                'promo_marca': promo_marca,
                'fecha_inicio': fecha_inicio,
                'fecha_finalizacion': fecha_finalizacion,
                'tipo_licencia': tipo_licencia,
                'vencimiento_licencia': vencimiento_licencia,
                'tarjeta_seguro': tarjeta_seguro,
                'fecha_servicio_anterior': fecha_servicio_anterior,
            }

            # 3. Recoger resultados del checklist y APLICAR VALIDACIÓN ESTRICTA
            checklist_results = {}
            for category, items in CHECKLIST_ITEMS:
                for item in items:
                    # Construcción de la clave de formulario limpia
                    form_key = 'check_' + item.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace(',', '').replace('-', '').replace('.', '')
                    
                    if form_key in request.form:
                        estado_value = request.form[form_key]
                        estado_normalizado = estado_value.lower().strip()

                        if estado_normalizado not in ESTADOS_VALIDOS_NORMALIZADOS:
                            raise ValueError(f"ERROR DE CALIFICACIÓN: El ítem '{item}' debe ser calificado como 'Buen Estado', 'Mal Estado' o 'N/A'. Se detectó un valor no permitido: '{estado_value}'.")
                        
                        # El db_manager espera un diccionario con 'categoria' y 'estado'
                        checklist_results[item] = {
                            'categoria': category,
                            'estado': estado_value # Valor original ('Buen Estado', 'Mal Estado', 'N/A')
                        }
                    else:
                        raise ValueError(f"Falta seleccionar el estado para el ítem obligatorio: {item}")
            
            # 4. Guardar en la DB
            db_manager.save_report_web(
                session['user_id'],
                report_data,
                checklist_results,
                observations,
                signature_confirmation
            )

            flash('Reporte de inspección guardado exitosamente.', 'success')
            return redirect(url_for('pilot_form'))

        except ValueError as e:
            flash(f'Error de validación: {e}', 'danger')
        except Exception as e:
            flash(f'Error al guardar el reporte: {e}', 'danger')

    return render_template('pilot_form.html', pilot_data=pilot_data, checklist=CHECKLIST_ITEMS)

# --- Rutas de Administración (Pilotos) ---

@app.route('/admin/pilots', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_pilots_web():
    pilots = db_manager.get_all_pilots()
    
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')

        try:
            if action == 'add':
                db_manager.manage_user_web(
                    action,
                    full_name=request.form['full_name'],
                    username=request.form['username'],
                    password=request.form['password']
                )
                flash('Piloto añadido exitosamente.', 'success')
            elif action in ['delete', 'toggle_status']:
                status = request.form.get('status')
                db_manager.manage_user_web(action, user_id=user_id, status=status)
                flash(f'Piloto {action} exitosamente.', 'success')
            
            return redirect(url_for('manage_pilots_web')) 

        except ValueError as e:
            flash(f"Error: {e}", 'danger')
        except Exception as e:
            flash(f"Error al procesar la solicitud: {e}", 'danger')
            
    # 🛑 CORRECCIÓN: Se envía la variable 'pilots' que es la que trae los datos.
    return render_template('admin_pilots.html', pilots=pilots)


# --- Rutas de Administración (Vehículos) ---

@app.route('/admin/vehicles', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_vehicles_web():
    vehicles = db_manager.get_all_vehicles()
    pilots = db_manager.get_all_pilots()

    if request.method == 'POST':
        action = request.form.get('action')
        plate = request.form.get('plate')

        try:
            if action == 'add':
                db_manager.manage_vehicle(
                    action,
                    plate=request.form['plate'],
                    brand=request.form['brand'],
                    model=request.form['model'],
                    year=request.form['year'],
                    capacity_kg=request.form['capacity_kg']
                )
                flash('Vehículo añadido exitosamente.', 'success')
            elif action == 'assign':
                pilot_id = request.form.get('pilot_id')
                db_manager.manage_vehicle(action, plate=plate, pilot_id=pilot_id)
                flash(f'Vehículo asignado exitosamente.', 'success')
            elif action == 'delete':
                db_manager.manage_vehicle(action, plate=plate)
                flash('Vehículo eliminado exitosamente.', 'success')

        except ValueError as e:
            flash(f"Error: {e}", 'danger')
        except Exception as e:
            flash(f"Error al procesar la solicitud: {e}", 'danger')
            
        return redirect(url_for('manage_vehicles_web'))

    return render_template('admin_vehicles.html', vehicles=vehicles, pilots=pilots)


# --- Rutas de Reportes (Visualización y Eliminación) ---

@app.route('/admin/reports', methods=['GET'])
@login_required
@admin_required
def admin_reports():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id_str = request.args.get('pilot_id')
    plate = request.args.get('plate')
    
    # NOTA: Usar 'a' y 'admin' para verificar el rol
    is_admin = session.get('role', '').lower() in ('admin', 'a')
    pilot_id = int(pilot_id_str) if pilot_id_str and pilot_id_str.isdigit() else None
    pilots = []

    if not is_admin:
        pilot_id = session['user_id']
        pilot_id_str = str(session['user_id'])
    else:
        try:
            pilots = db_manager.get_all_pilots()
        except Exception:
            pilots = []

    filters = {
        'start_date': start_date if start_date else '',
        'end_date': end_date if end_date else '',
        'pilot_id': pilot_id_str if pilot_id_str else '',
        'plate': plate if plate else ''
    }

    try:
        reports = db_manager.get_filtered_reports(start_date, end_date, pilot_id, plate)
        
        # CONVERSIÓN DE TIMESTAMP A STRING PARA JINJA
        reports_processed = []
        for report in reports:
            if hasattr(report['report_date'], 'strftime'):
                report['report_date'] = report['report_date'].strftime('%Y-%m-%d %H:%M:%S')
            
            reports_processed.append(report)

    except Exception as e:
        flash(f"Error al cargar datos: {e}", 'danger')
        reports_processed = []

    # Serializar reportes para el JavaScript (reports_json)
    reports_json = json.dumps(reports_processed, default=str)

    return render_template('admin_reports.html',
                            reports=reports_processed,
                            pilots=pilots,
                            filters=filters,
                            reports_json=reports_json)


@app.route('/admin/reports/delete/<int:report_id>', methods=['POST'])
@login_required
@admin_required
def delete_report_web(report_id):
    """Ruta para eliminar un reporte específico por su ID."""
    try:
        db_manager.delete_report(report_id)
        flash(f'Reporte ID {report_id} eliminado exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al eliminar el reporte: {e}', 'danger')
        
    return redirect(url_for('admin_reports'))


@app.route('/admin/reports/export', methods=['GET'])
@login_required
@admin_required
def export_reports():
    """Exporta los reportes filtrados a un archivo CSV."""
    
    # 1. Obtener filtros y seguridad (igual que admin_reports)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id_str = request.args.get('pilot_id')
    plate = request.args.get('plate')
    
    is_admin = session.get('role', '').lower() in ('admin', 'a')
    pilot_id = int(pilot_id_str) if pilot_id_str and pilot_id_str.isdigit() else None
    
    if not is_admin:
        pilot_id = session['user_id']
    
    # 2. Obtener datos filtrados y PROCESAR FECHAS
    try:
        reports = db_manager.get_filtered_reports(start_date, end_date, pilot_id, plate)
        
        # CONVERSIÓN DE TIMESTAMP A STRING para el CSV y JSON
        for report in reports:
            if hasattr(report['report_date'], 'strftime'):
                report['report_date'] = report['report_date'].strftime('%Y-%m-%d %H:%M:%S')

    except Exception as e:
        flash(f"Error al exportar datos: {e}", 'danger')
        return redirect(url_for('admin_reports'))

    if not reports:
        flash('No hay datos para exportar con los filtros seleccionados.', 'info')
        return redirect(url_for('admin_reports'))
        
    # 3. Preparar la respuesta CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Encabezados del CSV
    writer.writerow([
        'ID_Reporte', 'Fecha_Reporte', 'Piloto', 'ID_Piloto', 'Placa_Vehiculo',
        'KM_Actual', 'Observaciones', 'Header_JSON', 'Detalles_Checklist_JSON'
    ])

    # 4. Datos
    for report in reports:
        row = [
            report['id'],
            report['report_date'],
            report['pilot_name'],
            report['driver_id'],
            report['vehicle_plate'],
            report['km_actual'],
            report['observations'],
            json.dumps(report['header_data'], default=str),
            json.dumps(report['checklist_details'], default=str)
        ]
        writer.writerow(row)
        
    output.seek(0)
    
    response = make_response(output.getvalue())
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"reportes_inspeccion_{now}.csv"
    
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = "text/csv"
    return response

# --- Inicialización de la DB y Ejecución ---

try:
    db_manager.inicializar_db()
    print("Base de datos inicializada/verificada.")
except Exception as e:
    print(f"ERROR CRÍTICO DE CONEXIÓN EN INICIALIZACIÓN: {e}")

if __name__ == '__main__':
    app.run(debug=True)
