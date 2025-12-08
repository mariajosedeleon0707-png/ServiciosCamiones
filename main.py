import csv
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
# Importaciones de módulos locales (config y db_manager)
from config import SECRET_KEY, CHECKLIST_ITEMS 
import db_manager 
from config import SECRET_KEY, CHECKLIST_ITEMS
import db_manager

# --- Inicialización de la Aplicación ---
app = Flask(__name__)
app.secret_key = SECRET_KEY 
app.secret_key = SECRET_KEY

# --- CONSTANTE DE ESTADOS VÁLIDOS ---
# 🎉 CORRECCIÓN FINAL: Se incluyen "N/A"
ESTADOS_VALIDOS = ["Buen Estado", "Mal Estado", "N/A"] 
# Se pre-normalizan los estados válidos para una validación más rápida y robusta
ESTADOS_VALIDOS = ["Buen Estado", "Mal Estado", "N/A"]
ESTADOS_VALIDOS_NORMALIZADOS = [s.lower().strip() for s in ESTADOS_VALIDOS]
# ------------------------------------

@@ -25,11 +23,12 @@ def format_thousand_separator(value):
    """
    try:
        # Convertir a entero y formatear con coma (separador por defecto en Python/US)
        # Esto maneja los casos como '1000' -> '1,000'
        formatted = f"{int(value):,}"
        # Reemplazar la coma por un punto para el formato español/Latinoamericano
        return formatted.replace(',', '.')
    except (ValueError, TypeError):
        return str(value) 
        return str(value)

app.jinja_env.filters['separator'] = format_thousand_separator
# 🛠️ --- FIN FILTROS PERSONALIZADOS DE JINJA ---
@@ -72,7 +71,7 @@ def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        

        user = db_manager.get_user_by_credentials(username, password)

        if user and user.get('is_active') == 1:
@@ -85,7 +84,7 @@ def login():
            flash("Su cuenta ha sido deshabilitada. Contacte al administrador.", 'danger')
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')
            

    return render_template('login.html')

@app.route('/logout')
@@ -102,36 +101,36 @@ def pilot_form():
    if session.get('role') != 'piloto':
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('home'))
        

    pilot_data = db_manager.load_pilot_data(session['user_id'])
    

    if not pilot_data or not pilot_data.get('plate'):
        return render_template('pilot_form.html', error="No tiene un vehículo asignado. Contacte a su administrador.", pilot_data=None)

    if request.method == 'POST':
        try:
            # 1. VALIDACIÓN Y RECOLECCIÓN DE DATOS GENERALES
            

            # --- KM Actual (Validación Numérica y de Vacío) ---
            km_actual_str = request.form.get('km_actual')
            if not km_actual_str:
                raise ValueError("El campo Kilometraje Actual es obligatorio.")
            try:
                # Convertir a float después de la validación
                # Convertir a float
                km_actual = float(km_actual_str)
            except ValueError:
                raise ValueError("El Kilometraje Actual debe ser un número válido.")
            # ----------------------------------------------------
            

            observations = request.form.get('observations', '')
            

            # --- Firma (Validación de Obligatoriedad) ---
            signature_confirmation = request.form.get('signature_confirmation')
            if signature_confirmation is None: # Si el checkbox no fue marcado, es None
                raise ValueError("Debe confirmar con la firma (checkbox) para enviar el reporte.")
            # ------------------------------------------

            # Recoger los demás campos, asumiendo que son opcionales si no se validan aquí.
            # Recoger los demás campos
            promo_marca = request.form.get('promo_marca', '')
            fecha_inicio = request.form.get('fecha_inicio', '')
            fecha_finalizacion = request.form.get('fecha_finalizacion', '')
@@ -159,48 +158,52 @@ def pilot_form():
                'fecha_servicio_anterior': fecha_servicio_anterior,
            }

            # 3. Recoger resultados del checklist y APLICAR VALIDACIÓN ESTRICTA (CORREGIDA)
            # 3. Recoger resultados del checklist y APLICAR VALIDACIÓN ESTRICTA
            checklist_results = {}
            for category, items in CHECKLIST_ITEMS:
                for item in items:
                    # Construcción de la clave de formulario limpia
                    form_key = 'check_' + item.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace(',', '').replace('-', '').replace('.', '')
                    

                    # Si la clave NO está en request.form, significa que no se marcó NINGÚN radio button
                    if form_key in request.form:
                        estado_value = request.form[form_key]
                        

                        # 🌟 CORRECCIÓN CLAVE: Normalizar el valor recibido para la validación
                        estado_normalizado = estado_value.lower().strip() 
                        estado_normalizado = estado_value.lower().strip()

                        if estado_normalizado not in ESTADOS_VALIDOS_NORMALIZADOS:
                            # Se lanza el error si el valor no es válido. 
                            # Se actualiza el mensaje para incluir "N/A"
                            raise ValueError(f"ERROR DE CALIFICACIÓN: El ítem '{item}' debe ser calificado como 'Buen Estado', 'Mal Estado' o 'N/A'. Se detectó un valor no permitido: '{estado_value}'.")
                        
                        # Se guarda el valor original recibido del formulario
                        # Esto guarda 'Buen Estado', 'Mal Estado' o 'N/A' exactamente como se envió.
                        checklist_results[item] = estado_value 
                            raise ValueError(f"ERROR DE CALIFICACIÓN: El ítem '{item}' debe ser calificado como 'Buen Estado', 'Mal Estado' o 'N/A'.")

                        # ✅ CORRECCIÓN 1: Adaptar el formato para db_manager.save_report_web
                        # El db_manager espera un diccionario con 'categoria' y 'estado'
                        checklist_results[item] = {
                            'categoria': category,
                            'estado': estado_value # Valor original ('Buen Estado', 'Mal Estado', 'N/A')
                        }
                    else:
                        # Esto atrapa el caso en que un ítem obligatorio no fue seleccionado
                        raise ValueError(f"Falta seleccionar el estado para el ítem obligatorio: {item}")
            


            # 4. Guardar en la DB
            db_manager.save_report_web(
                session['user_id'], 
                report_data, 
                checklist_results, 
                observations, 
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
            # Errores críticos de DB, ej. Violación de Foreign Key, problemas de conexión
            flash(f'Error al guardar el reporte: {e}', 'danger')
            

    return render_template('pilot_form.html', pilot_data=pilot_data, checklist=CHECKLIST_ITEMS)

# --- Rutas de Administración (Usuarios y Vehículos) ---
@@ -211,21 +214,21 @@ def manage_pilots_web():
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')
        

        try:
            if action == 'add':
                db_manager.manage_user_web(
                    action, 
                    full_name=request.form['full_name'], 
                    username=request.form['username'], 
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
@@ -241,7 +244,7 @@ def manage_vehicles_web():
    if request.method == 'POST':
        action = request.form.get('action')
        plate = request.form.get('plate')
        

        try:
            if action == 'add':
                db_manager.manage_vehicle(
@@ -276,7 +279,7 @@ def manage_vehicles_web():
            elif action == 'delete':
                db_manager.manage_vehicle(action, plate=plate)
                flash('Vehículo eliminado exitosamente.', 'success')
            

        except ValueError as e:
            flash(f"Error: {e}", 'danger')
        except Exception as e:
@@ -290,27 +293,29 @@ def manage_vehicles_web():
# --- Rutas de Reportes (Seguridad y Conversión de Fecha Corregida) ---

@app.route('/admin/reports', methods=['GET'])
@login_required 
@login_required
def admin_reports():
    # 1. Obtener filtros y definir seguridad
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id_str = request.args.get('pilot_id')
    plate = request.args.get('plate')
    

    is_admin = session.get('role') == 'admin'
    pilot_id = int(pilot_id_str) if pilot_id_str and pilot_id_str.isdigit() else None
    pilots = [] 
    pilots = []

    if not is_admin:
        # Si no es admin, solo puede ver sus propios reportes
        pilot_id = session['user_id']
        pilot_id_str = str(session['user_id']) 
        pilot_id_str = str(session['user_id'])
    else:
        # Si es admin, puede ver todos o cargar la lista de pilotos para el filtro
        try:
            pilots = db_manager.get_all_pilots()
        except Exception:
            pilots = []
            

    filters = {
        'start_date': start_date if start_date else '',
        'end_date': end_date if end_date else '',
@@ -321,34 +326,34 @@ def admin_reports():
    # 3. Obtener datos filtrados y PROCESAR FECHAS
    try:
        reports = db_manager.get_filtered_reports(start_date, end_date, pilot_id, plate)
        
        # === CORRECCIÓN DE TIMESTAMP A STRING PARA JINJA (Resuelve el UndefinedError) ===

        # === CONVERSIÓN DE TIMESTAMP A STRING PARA JINJA (Resuelve el UndefinedError) ===
        reports_processed = []
        for report in reports:
            # Si report_date es un objeto Timestamp, lo convertimos a string
            if hasattr(report['report_date'], 'strftime'):
                report['report_date'] = report['report_date'].strftime('%Y-%m-%d %H:%M:%S')
            

            reports_processed.append(report)
        # =================================================================================

    except Exception as e:
        flash(f"Error al cargar datos: {e}", 'danger')
        reports_processed = []
        

    # 4. Serializar reportes para el JavaScript (reports_json)
    reports_json = json.dumps(reports_processed, default=str) 
        
    reports_json = json.dumps(reports_processed, default=str)

    # 5. Renderizar la plantilla
    return render_template('admin_reports.html', 
                            reports=reports_processed, 
                            pilots=pilots, 
    return render_template('admin_reports.html',
                            reports=reports_processed,
                            pilots=pilots,
                            filters=filters,
                            reports_json=reports_json)


@app.route('/admin/reports/delete/<int:report_id>', methods=['POST'])
@admin_required 
@admin_required
def delete_report_web(report_id):
    """
    Ruta para eliminar un reporte específico por su ID.
@@ -358,31 +363,31 @@ def delete_report_web(report_id):
        flash(f'Reporte ID {report_id} eliminado exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al eliminar el reporte: {e}', 'danger')
        

    return redirect(url_for('admin_reports'))


@app.route('/admin/reports/export', methods=['GET'])
@login_required 
@login_required
def export_reports():
    """Exporta los reportes filtrados a un archivo CSV."""
    

    # 1. Obtener filtros y seguridad (igual que admin_reports)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    pilot_id_str = request.args.get('pilot_id')
    plate = request.args.get('plate')
    

    is_admin = session.get('role') == 'admin'
    pilot_id = int(pilot_id_str) if pilot_id_str and pilot_id_str.isdigit() else None
    

    if not is_admin:
        pilot_id = session['user_id']
    

    # 2. Obtener datos filtrados y PROCESAR FECHAS
    try:
        reports = db_manager.get_filtered_reports(start_date, end_date, pilot_id, plate)
        

        # === CONVERSIÓN DE TIMESTAMP A STRING para el CSV y JSON ===
        for report in reports:
            if hasattr(report['report_date'], 'strftime'):
@@ -391,31 +396,33 @@ def export_reports():

    except Exception as e:
        flash(f"Error al exportar datos: {e}", 'danger')
        return redirect(url_for('admin_reports')) 
        return redirect(url_for('admin_reports'))

    # 3. Preparar la respuesta CSV
    output = io.StringIO()
    writer = csv.writer(output)
    

    # Encabezados del CSV
    # ✅ CORRECCIÓN 2: Cambiado 'Checklist_JSON' por 'Detalles_Checklist_JSON'
    writer.writerow([
        'ID_Reporte', 'Fecha_Reporte', 'Piloto', 'ID_Piloto', 'Placa_Vehiculo', 
        'KM_Actual', 'Observaciones', 'Header_JSON', 'Checklist_JSON'
        'ID_Reporte', 'Fecha_Reporte', 'Piloto', 'ID_Piloto', 'Placa_Vehiculo',
        'KM_Actual', 'Observaciones', 'Header_JSON', 'Detalles_Checklist_JSON'
    ])

    # 4. Datos 
    # 4. Datos
    for report in reports:
        # report['report_date'] ahora es un string limpio
        # ✅ CORRECCIÓN 2: Cambiado report['checklist_data'] por report['checklist_details']
        row = [
            report['id'],
            report['report_date'], 
            report['pilot_name'], 
            report['driver_id'], 
            report['vehicle_plate'], 
            report['report_date'],
            report['pilot_name'],
            report['driver_id'],
            report['vehicle_plate'],
            report['km_actual'],
            report['observations'], 
            report['observations'],
            json.dumps(report['header_data'], default=str),
            json.dumps(report['checklist_data'], default=str)
            json.dumps(report['checklist_details'], default=str)
        ]
        writer.writerow(row)

@@ -430,6 +437,9 @@ def export_reports():
try:
    db_manager.inicializar_db()
except Exception as e:
    # Esto evita que la aplicación se caiga si falla la conexión a la DB, 
    # Esto evita que la aplicación se caiga si falla la conexión a la DB,
    # pero permite que las rutas arrojen el error apropiado.
    print(f"ERROR CRÍTICO DE CONEXIÓN EN INICIALIZACIÓN: {e}")

if __name__ == '__main__':
    app.run(debug=True)
