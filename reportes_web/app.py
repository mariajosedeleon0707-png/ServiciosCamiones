import json
import functools
import io
import csv
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
from config import SECRET_KEY, CHECKLIST_ITEMS 
import db_manager 

# --- Inicialización de la Aplicación ---
app = Flask(__name__)
app.secret_key = SECRET_KEY 

# 🛠️ --- FILTROS PERSONALIZADOS DE JINJA (SOLUCIÓN ERROR 1) ---
def format_thousand_separator(value):
    """
    Filtro para añadir separador de miles (punto) en Jinja.
    """
    try:
        # Convertir a entero y formatear con coma (separador por defecto en Python/US)
        formatted = f"{int(value):,}"
        # Reemplazar la coma por un punto para el formato español/Latinoamericano
        return formatted.replace(',', '.')
    except (ValueError, TypeError):
        return str(value) 

app.jinja_env.filters['separator'] = format_thousand_separator
# 🛠️ --- FIN FILTROS PERSONALIZADOS DE JINJA ---

# --- Decoradores ---

def admin_required(f):
    """Decorador para restringir el acceso solo a usuarios con rol 'admin'."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Acceso denegado. Se requiere ser administrador.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    """Decorador para restringir el acceso a usuarios no autenticados."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, inicie sesión para acceder.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Rutas de Autenticación y Home ---

@app.route('/')
def home():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return render_template('admin_base.html')
        elif session.get('role') == 'piloto':
            return redirect(url_for('pilot_form'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = db_manager.get_user_by_credentials(username, password)

        if user and user.get('is_active') == 1:
            session['user_id'] = user['id']
            session['user_name'] = user['full_name']
            session['role'] = user['role']
            flash(f"Bienvenido, {user['full_name']}!", 'success')
            return redirect(url_for('home'))
        elif user and user.get('is_active') == 0:
            flash("Su cuenta ha sido deshabilitada. Contacte al administrador.", 'danger')
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('login'))

# --- Rutas de Piloto ---

@app.route('/pilot/form', methods=['GET', 'POST'])
@login_required
def pilot_form():
    if session.get('role') != 'piloto':
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('home'))
        
    pilot_data = db_manager.load_pilot_data(session['user_id'])
    
    # Validación clave: si el piloto no tiene vehículo, no puede reportar
    if not pilot_data or not pilot_data.get('plate'):
        return render_template('pilot_form.html', error="No tiene un vehículo asignado. Contacte a su administrador.", pilot_data=None)

    if request.method == 'POST':
        try:
            # 1. Recoger datos generales y los nuevos campos del PDF (Asumimos que están en pilot_form.html)
            km_actual = float(request.form['km_actual'])
            observations = request.form.get('observations', '')
            signature_confirmation = request.form.get('signature_confirmation')
            
            # Recoger los nuevos campos del PDF (Se usan .get() para evitar errores si no están en el HTML)
            promo_marca = request.form.get('promo_marca', '')
            fecha_inicio = request.form.get('fecha_inicio', '')
            fecha_finalizacion = request.form.get('fecha_finalizacion', '')
            tipo_licencia = request.form.get('tipo_licencia', '')
            vencimiento_licencia = request.form.get('vencimiento_licencia', '')
            tarjeta_seguro = request.form.get('tarjeta_seguro', '')
            km_proximo_servicio = request.form.get('km_proximo_servicio', '')
            fecha_servicio_anterior = request.form.get('fecha_servicio_anterior', '')


            # 2. Recoger datos del encabezado (Header Data)
            report_data = {
                'plate': pilot_data['plate'],
                'brand': pilot_data['brand'],
                'model': pilot_data['model'],
                'km_actual': km_actual,
                # Se incluyen los nuevos datos para guardarlos en header_data si se modifica db_manager.save_report_web
                'promo_marca': promo_marca,
                'fecha_inicio': fecha_inicio,
                'fecha_finalizacion': fecha_finalizacion,
                'tipo_licencia': tipo_licencia,
                'vencimiento_licencia': vencimiento_licencia,
                'tarjeta_seguro': tarjeta_seguro,
                'km_proximo_servicio': km_proximo_servicio,
                'fecha_servicio_anterior': fecha_servicio_anterior,
            }

            # 3. Recoger resultados del checklist
            checklist_results = {}
            for category, items in CHECKLIST_ITEMS:
                for item in items:
                    # Normalizamos el nombre del ítem para que coincida con el HTML
                    form_key = 'check_' + item.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace(',', '').replace('-', '').replace('.', '')
                    
                    if form_key in request.form:
                        checklist_results[item] = request.form[form_key]
                    else:
                        raise ValueError(f"Falta seleccionar el estado para el ítem: {item}")
            
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

# --- Rutas de Administración (Usuarios y Vehículos) ---

@app.route('/admin/pilots', methods=['GET', 'POST'])
@admin_required
def manage_pilots_web():
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
            
        except ValueError as e:
            flash(f"Error: {e}", 'danger')
        except Exception as e:
            flash(f"Error inesperado: {e}", 'danger')

    users = db_manager.get_all_pilots()
    return render_template('admin_pilots.html', users=users)


@app.route('/admin/vehicles', methods=['GET', 'POST'])
@admin_required
def manage_vehicles_web():
    if request.method == 'POST':
        action = request.form.get('action')
        plate = request.form.get('plate')
        
        try:
            if action == 'add':
                db_manager.manage_vehicle(
                    action,
                    plate=plate,
                    brand=request.form['brand'],
                    model=request.form['model'],
                    year=request.form['year'],
                    capacity_kg=request.form['capacity_kg']
                )
                flash('Vehículo añadido exitosamente.', 'success')
            elif action == 'update':
                db_manager.manage_vehicle(
                    action,
                    plate=plate,
                    brand=request.form['brand'],
                    model=request.form['model'],
                    year=request.form['year'],
                    capacity_kg=request.form['capacity_kg']
                )
                flash('Vehículo actualizado exitosamente.', 'success')
            elif action == 'assign':
                db_manager.manage_vehicle(
                    action,
                    plate=plate,
                    assign_pilot_id=request.form['pilot_id']
                )
                flash('Piloto asignado exitosamente.', 'success')
            elif action == 'unassign':
                db_manager.manage_vehicle(action, plate=plate)
                flash('Piloto desasignado exitosamente.', 'success')
            elif action == 'delete':
                db_manager.manage_vehicle(action, plate=plate)
                flash('Vehículo eliminado exitosamente.', 'success')
        
        except ValueError as e:
            flash(f"Error: {e}", 'danger')
        except Exception as e:
            flash(f"Error inesperado: {e}", 'danger')

    vehicles = db_manager.get_all_vehicles()
    pilots = db_manager.get_all_pilots()
    return render_template('admin_vehicles.html', vehicles=vehicles, pilots=pilots)


# --- Rutas de Reportes ---

@app.route('/admin/reports', methods=['GET'])
@admin_required
def review_reports_web():
    """Muestra la interfaz de revisión de reportes con filtros y paginación."""
    
    # 1. Obtener filtros de la URL (request.args)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id_str = request.args.get('pilot_id')
    pilot_id = int(pilot_id_str) if pilot_id_str and pilot_id_str.isdigit() else None
    plate = request.args.get('plate')
    
    # Guardar los filtros para pasarlos de vuelta a la plantilla y mantener la selección
    filters = {
        'start_date': start_date if start_date else '',
        'end_date': end_date if end_date else '',
        'pilot_id': pilot_id_str if pilot_id_str else '',
        'plate': plate if plate else ''
    }

    # 2. Obtener datos filtrados
    try:
        reports = db_manager.get_filtered_reports(start_date, end_date, pilot_id, plate)
        pilots = db_manager.get_all_pilots()
        vehicles = db_manager.get_all_vehicles()
    except Exception as e:
        flash(f"Error al cargar datos: {e}", 'danger')
        reports = []
        pilots = []
        vehicles = []
        
    # 3. Serializar reportes para el JavaScript (reports_json)
    reports_json = json.dumps(reports) 
    
    # 4. Renderizar la plantilla
    return render_template('admin_reports.html', 
                           reports=reports, 
                           pilots=pilots, 
                           vehicles=vehicles,
                           filters=filters,
                           reports_json=reports_json)


@app.route('/admin/reports/delete/<int:report_id>', methods=['POST'])
@admin_required
def delete_report_web(report_id):
    """
    Ruta para eliminar un reporte específico por su ID.
    ESTA RUTA SOLUCIONA EL BUILDERROR.
    """
    try:
        db_manager.delete_report(report_id)
        flash(f'Reporte ID {report_id} eliminado exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al eliminar el reporte: {e}', 'danger')
        
    # Redirigir a la página de reportes. Si quieres mantener los filtros
    # activos después de la eliminación, tu formulario de eliminación
    # en admin_reports.html debe incluir los filtros como campos ocultos.
    return redirect(url_for('review_reports_web'))


@app.route('/admin/reports/export', methods=['GET'])
@admin_required
def export_reports():
    """Exporta los reportes filtrados a un archivo CSV."""
    
    # 1. Obtener filtros de la URL
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id_str = request.args.get('pilot_id')
    pilot_id = int(pilot_id_str) if pilot_id_str and pilot_id_str.isdigit() else None
    plate = request.args.get('plate')
    
    # 2. Obtener los datos filtrados
    try:
        reports = db_manager.get_filtered_reports(start_date, end_date, pilot_id, plate)
    except Exception as e:
        flash(f"Error al exportar datos: {e}", 'danger')
        return redirect(url_for('review_reports_web'))

    # 3. Preparar la respuesta CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Encabezados del CSV (Asegúrate de que coincidan con las claves devueltas por get_filtered_reports)
    writer.writerow([
        'ID_Reporte', 'Fecha_Reporte', 'Piloto', 'ID_Piloto', 'Placa_Vehiculo', 
        'KM_Actual', 'Observaciones', 'Header_JSON', 'Checklist_JSON'
    ])

    # 4. Datos 
    for report in reports:
        # Asegúrate de que las claves existan en los diccionarios de reportes
        row = [
            report['id'],
            report['report_date'], 
            report['pilot_name'], 
            report['driver_id'], 
            report['vehicle_plate'], 
            report['km_actual'],
            report['observations'], 
            json.dumps(report['header_data']), 
            json.dumps(report['checklist_data'])
        ]
        writer.writerow(row)

    # 5. Crear el objeto Response para la descarga
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=reportes_inspeccion.csv'
    return response

# --- Ejecución de la App ---
if __name__ == '__main__':
    # Asegúrate de que la DB se inicialice antes de correr la app
    db_manager.inicializar_db()
    app.run(debug=True)