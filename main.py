import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from functools import wraps
from datetime import datetime
import db_manager
import json

# --- Configuración de la Aplicación ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default_secret_key_change_me')

# Inicializar la base de datos al inicio
try:
    db_manager.inicializar_db()
except Exception as e:
    print(f"Error al inicializar la base de datos: {e}")

# --- Decoradores de Seguridad ---

def login_required(f):
    """Restringe el acceso a usuarios no autenticados."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Restringe el acceso solo a usuarios con rol 'a' (Administrador)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'a':
            flash('Acceso denegado. Se requiere rol de Administrador.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- Rutas Públicas ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = db_manager.get_user_by_credentials(username, password)
        
        if user and user.get('is_active', 1) == 1:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            
            flash(f'Bienvenido, {user["full_name"]}.', 'success')
            
            if user['role'] == 'a':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('pilot_form_web'))
        else:
            flash('Credenciales incorrectas o usuario inactivo.', 'danger')
            return render_template('login.html')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('Has cerrado sesión.', 'success')
    return redirect(url_for('login'))

# --- Rutas de Pilotos ---

@app.route('/')
@login_required
def home():
    if session.get('role') == 'a':
        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('pilot_form_web'))

@app.route('/pilot/report', methods=['GET', 'POST'])
@login_required
def pilot_form_web():
    user_id = session['user_id']
    
    if request.method == 'POST':
        try:
            # 1. Extracción y Preparación de Datos
            header_data = {
                'plate': request.form.get('vehicle_plate'),
                'driver_name': session['full_name'],
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'license': request.form.get('license'),
                'promotion': request.form.get('promotion')
            }
            
            km_actual = float(request.form.get('km_actual', 0))
            km_proximo_servicio = request.form.get('km_proximo_servicio')
            fecha_servicio_anterior = request.form.get('fecha_servicio_anterior')
            observations = request.form.get('observations')
            signature_confirmation = request.form.get('signature_confirmation') == 'on'

            # 2. Checklist (asume un formato de item_nombre: estado_string)
            checklist_results = {}
            for key, value in request.form.items():
                if key.startswith('item_'):
                    # El nombre del campo es item_[categoría]_[nombre_item]
                    parts = key.split('_', 2)
                    if len(parts) == 3:
                        categoria = parts[1]
                        item_name = parts[2]
                        checklist_results[item_name] = {
                            'categoria': categoria,
                            'estado': value 
                        }

            # 3. Guardar en DB
            db_manager.save_report_web(
                driver_id=user_id,
                header_data=header_data,
                checklist_results=checklist_results,
                observations=observations,
                signature_confirmation=signature_confirmation
            )

            flash('Reporte de inspección guardado exitosamente.', 'success')
            return redirect(url_for('pilot_form_web'))

        except ValueError as e:
            flash(f'Error de datos: {e}', 'danger')
        except Exception as e:
            flash(f'Error al procesar el reporte: {e}', 'danger')


    # Lógica GET
    pilot_data = db_manager.load_pilot_data(user_id)
    
    if not pilot_data or not pilot_data.get('plate'):
        flash('No tienes un vehículo asignado. Contacta al administrador.', 'danger')
        # Podemos cargar una plantilla de error o el mismo formulario, pero sin datos de vehículo
        return render_template('pilot_form.html', pilot_data=None)

    # El resto del código de render_template asume que pilot_data tiene 'plate', 'full_name', etc.
    return render_template('pilot_form.html', pilot_data=pilot_data)

# --- Rutas de Administrador ---

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    # El dashboard puede mostrar un resumen de reportes, pilotos, etc.
    # Por ahora, solo redirige a la gestión de vehículos.
    return redirect(url_for('manage_vehicles_web'))


@app.route('/admin/pilots', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_pilots_web():
    # Manejar las acciones de POST (Añadir, Eliminar, Activar/Desactivar)
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')
        
        try:
            if action == 'add':
                username = request.form['username']
                full_name = request.form['full_name']
                password = request.form['password']
                db_manager.manage_user_web(action='add', username=username, full_name=full_name, password=password)
                flash('Piloto añadido exitosamente.', 'success')
            
            elif action == 'delete':
                db_manager.manage_user_web(action='delete', user_id=user_id)
                flash('Piloto eliminado exitosamente.', 'warning')
            
            elif action == 'toggle_status':
                status = request.form['status']
                db_manager.manage_user_web(action='toggle_status', user_id=user_id, status=status)
                flash('Estado del piloto actualizado.', 'info')

        except ValueError as e:
            flash(f'Error de datos: {e}', 'danger')
        except Exception as e:
            flash(f'Error al gestionar piloto: {e}', 'danger')
            return redirect(url_for('manage_pilots_web')) # Redirige incluso con error para mostrar flash

    # Lógica GET
    pilots_list = db_manager.get_all_pilots()
    
    # 🛑 CRÍTICO: Envía la lista como 'users' para que coincida con tu HTML
    return render_template('admin_pilots.html', users=pilots_list)


@app.route('/admin/vehicles', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_vehicles_web():
    if request.method == 'POST':
        action = request.form.get('action')
        plate = request.form.get('plate')
        
        try:
            if action == 'add':
                db_manager.manage_vehicle(action='add', 
                                         plate=request.form['plate'], 
                                         brand=request.form['brand'], 
                                         model=request.form['model'], 
                                         year=request.form['year'], 
                                         capacity_kg=request.form['capacity_kg'])
                flash('Vehículo añadido exitosamente.', 'success')
            
            elif action == 'update':
                 db_manager.manage_vehicle(action='update', 
                                         plate=plate, 
                                         brand=request.form['brand'], 
                                         model=request.form['model'], 
                                         year=request.form['year'], 
                                         capacity_kg=request.form['capacity_kg'])
                 flash('Vehículo actualizado exitosamente.', 'success')
            
            elif action == 'assign':
                pilot_id = request.form['pilot_id']
                db_manager.manage_vehicle(action='assign', plate=plate, pilot_id=pilot_id)
                flash(f'Vehículo {plate} asignado.', 'success')
            
            elif action == 'unassign':
                db_manager.manage_vehicle(action='unassign', plate=plate)
                flash(f'Vehículo {plate} desasignado.', 'info')

            elif action == 'delete':
                db_manager.manage_vehicle(action='delete', plate=plate)
                flash(f'Vehículo {plate} eliminado.', 'warning')
            
        except Exception as e:
            flash(f'Error al gestionar el vehículo: {e}', 'danger')
            return redirect(url_for('manage_vehicles_web'))

    # Lógica GET
    vehicles = db_manager.get_all_vehicles()
    # Para el modal de asignación, necesitamos la lista de pilotos (solo los activos)
    pilots_for_dropdown = db_manager.get_all_pilots() 

    return render_template('admin_vehicles.html', vehicles=vehicles, pilots=pilots_for_dropdown)


@app.route('/admin/reports', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_reports_web():
    # Manejar eliminación de reportes
    if request.method == 'POST':
        action = request.form.get('action')
        report_id = request.form.get('report_id')
        
        if action == 'delete' and report_id:
            try:
                db_manager.delete_report(int(report_id))
                flash(f'Reporte #{report_id} eliminado exitosamente.', 'warning')
            except Exception as e:
                flash(f'Error al eliminar el reporte: {e}', 'danger')
            return redirect(url_for('manage_reports_web'))

    # Manejar filtros GET
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id = request.args.get('pilot_id')
    plate = request.args.get('plate')
    
    reports = db_manager.get_filtered_reports(start_date, end_date, pilot_id, plate)
    
    # Datos necesarios para los filtros y las tablas
    pilots = db_manager.get_all_pilots()
    vehicles = db_manager.get_all_vehicles()
    
    return render_template('admin_reports.html', reports=reports, pilots=pilots, vehicles=vehicles)


@app.route('/admin/report/<int:report_id>')
@login_required
@admin_required
def view_report_detail(report_id):
    # Por simplificación, la función get_filtered_reports devuelve una lista
    # Usaremos esa misma función para obtener un reporte específico por su ID si es necesario,
    # pero es mejor tener una función separada get_report_by_id en db_manager.
    # Asumiendo que get_filtered_reports puede manejar el filtro solo por ID si fuera el caso,
    # o si report_id se pasa como parámetro de filtro.

    # Mejor: Adaptar la vista para que el reporte venga de la lista principal (si es posible)
    # o crear una función específica en db_manager.
    
    try:
        # Esto es solo un placeholder, la lógica real requeriría una función get_report_by_id
        # en db_manager o filtrar la lista completa. Para fines de demostración, 
        # asumimos que puedes obtener los detalles del reporte.
        
        # Simulando obtener el reporte si db_manager no tiene get_report_by_id
        all_reports = db_manager.get_filtered_reports() 
        report = next((r for r in all_reports if r['id'] == report_id), None)
        
        if report:
            # Puedes usar json.loads para asegurar que el JSONB se muestre correctamente
            report['header_data_formatted'] = json.dumps(report.get('header_data', {}), indent=2)
            report['checklist_details_formatted'] = json.dumps(report.get('checklist_details', []), indent=2)

            return render_template('admin_report_detail.html', report=report)
        else:
            flash(f'Reporte con ID {report_id} no encontrado.', 'danger')
            return redirect(url_for('manage_reports_web'))

    except Exception as e:
        flash(f'Error al cargar detalles del reporte: {e}', 'danger')
        return redirect(url_for('manage_reports_web'))


# --- Ejecución ---

if __name__ == '__main__':
    app.run(debug=True)
