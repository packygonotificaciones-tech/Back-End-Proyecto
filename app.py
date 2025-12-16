from flask import Flask, request, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from flask_cors import CORS
from db import get_connection
from werkzeug.security import generate_password_hash, check_password_hash
from auth import generate_token, verify_token, token_required, role_required
import os
import random
from datetime import datetime

from envioCorreos import (
    enviarCorreo,
    enviarCorreoCambio,
    enviarCorreoVerificacion,
    enviarCorreoReserva,
    enviarCorreoCancelacion 
)

from dotenv import load_dotenv
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

load_dotenv()
email_sender = "packygonotificaciones@gmail.com"
password = os.getenv("PASSWORD")

app = Flask(__name__)
# Enable CORS for API routes and allow credentials
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

@app.after_request
def add_cors_headers(response):
    # If Origin header is present, echo it back instead of using '*'.
    # Browsers disallow Access-Control-Allow-Credentials: true together with '*'.
    origin = request.headers.get('Origin')
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.setdefault("Access-Control-Allow-Credentials", "true")
    return response

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, "images")
PROFILE_FOLDER = os.path.join(IMAGES_FOLDER, "profiles")
DOCS_FOLDER = os.path.join(UPLOAD_FOLDER, "docs")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(IMAGES_FOLDER, exist_ok=True)
os.makedirs(DOCS_FOLDER, exist_ok=True)
os.makedirs(PROFILE_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

verification_codes = {}
reset_codes = {}

def redondear_hora(dt_str):
    dt = datetime.fromisoformat(dt_str)
    return dt.replace(minute=0, second=0, microsecond=0)

def build_user_dict(row):
    """
    Construye un dict de usuario a partir de una fila con el siguiente SELECT:
    SELECT id, primer_nombre, segundo_nombre, primer_apellido, segundo_apellido,
           tipoDocumento, noDocumento, correo, telefono, rol, fecha_registro, foto
    """
    if not row:
        return None
    return {
        "id": row[0],
        "primer_nombre": row[1],
        "segundo_nombre": row[2],
        "primer_apellido": row[3],
        "segundo_apellido": row[4],
        "tipoDocumento": row[5],
        "noDocumento": row[6],
        "correo": row[7],
        "telefono": row[8],
        "rol": row[9],
        "fecha_registro": row[10].isoformat() if row[10] else None,
        "foto": row[11],
    }

def get_user_by_correo(correo):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, primer_nombre, segundo_nombre, primer_apellido, segundo_apellido,
                   tipoDocumento, noDocumento, correo, telefono, rol, fecha_registro, foto
            FROM usuario
            WHERE correo=%s
            """,
            (correo,)
        )
        row = cursor.fetchone()
        return build_user_dict(row)
    finally:
        cursor.close()
        conn.close()

@app.route("/api/request-reset", methods=["POST"])
def request_reset():
    data = request.json
    correo = data.get("correo")
    if not correo:
        return {"error": "Correo es obligatorio"}, 400
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuario WHERE correo=%s", (correo,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if not user:
        return {"error": "No existe usuario con ese correo"}, 404
    codigo = str(random.randint(100000, 999999))
    reset_codes[correo] = codigo
    email_sent = enviarCorreo(correo, codigo, async_send=False)
    
    if email_sent:
        return {"message": "Código de recuperación enviado al correo."}, 200
    else:
        return {
            "message": "Código generado correctamente.", 
            "warning": "Hubo un problema enviando el correo. Usa el código: " + codigo
        }, 200

@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    data = request.json
    correo = data.get("correo")
    code = data.get("code")
    nueva = data.get("nueva")
    if not all([correo, code, nueva]):
        return {"error": "Todos los campos son obligatorios"}, 400
    codigo = reset_codes.get(correo)
    if not codigo or codigo != code:
        return {"error": "Código incorrecto"}, 400
    hashed_password = generate_password_hash(nueva)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE usuario SET contrasena=%s WHERE correo=%s", (hashed_password, correo))
        conn.commit()
        reset_codes.pop(correo)
        enviarCorreoCambio(correo, async_send=False)
        user = get_user_by_correo(correo)
        if user:
            return (user, 200)
        return {"message": "Contraseña actualizada exitosamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 400
    finally:
        cursor.close()
        conn.close()

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    primer_nombre = data.get("primer_nombre")
    segundo_nombre = data.get("segundo_nombre", "")
    primer_apellido = data.get("primer_apellido")
    segundo_apellido = data.get("segundo_apellido", "")
    noDocumento = data.get("noDocumento")
    tipoDocumento = data.get("tipoDocumento")
    correo = data.get("correo")
    telefono = data.get("telefono")
    contrasena = data.get("contrasena")
    rol = data.get("rol")

    if not all([primer_nombre, primer_apellido, noDocumento, tipoDocumento, correo, telefono, contrasena, rol]):
        return {"error": "Todos los campos obligatorios deben ser completados"}, 400

    # Verificar si ya existe un usuario con el mismo correo o número de documento
    conn_check = get_connection()
    cursor_check = conn_check.cursor()
    try:
        cursor_check.execute("SELECT id FROM usuario WHERE correo=%s", (correo,))
        if cursor_check.fetchone():
            return {"error": "El correo ya está registrado."}, 400
        cursor_check.execute("SELECT id FROM usuario WHERE noDocumento=%s", (noDocumento,))
        if cursor_check.fetchone():
            return {"error": "El documento ya está registrado."}, 400
    finally:
        cursor_check.close()
        conn_check.close()

    codigo = str(random.randint(100000, 999999))
    verification_codes[correo] = {
        "code": codigo,
        "data": {
            "primer_nombre": primer_nombre,
            "segundo_nombre": segundo_nombre,
            "primer_apellido": primer_apellido,
            "segundo_apellido": segundo_apellido,
            "noDocumento": noDocumento,
            "tipoDocumento": tipoDocumento,
            "correo": correo,
            "telefono": telefono,
            "contrasena": contrasena,
            "rol": rol
        }
    }
    enviarCorreo(correo, codigo, async_send=False)
    return {"message": "Código enviado. Verifica tu correo.", "correo": correo}, 200

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    correo = data.get("correo")
    contrasena = data.get("contrasena")

    if not correo or not contrasena:
        return {"error": "Correo y contraseña son obligatorios"}, 400

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuario WHERE correo=%s", (correo,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user and check_password_hash(user[9], contrasena):
        codigo = str(random.randint(100000, 999999))
        verification_codes[correo] = {
            "code": codigo,
            "user": {
                "id": user[0],
                "primer_nombre": user[1],
                "segundo_nombre": user[2],
                "primer_apellido": user[3],
                "segundo_apellido": user[4],
                "correo": user[7],
                "rol": user[10] 
            }
        }
        enviarCorreo(correo, codigo, async_send=False)
        return {"message": "Código enviado. Verifica tu correo.", "correo": correo}, 200
    else:
        return {"error": "Credenciales inválidas"}, 401

@app.route("/api/verify", methods=["POST"])
def verify():
    data = request.json
    correo = data.get("correo")
    code = data.get("code")
    tipo = data.get("tipo")

    if tipo == "reset":
        codigo = reset_codes.get(correo)
        if not codigo or codigo != code:
            return {"error": "Código incorrecto"}, 400
        return {"code": code, "message": "Código verificado"}, 200

    verif = verification_codes.get(correo)
    if not verif or verif["code"] != code:
        return {"error": "Código incorrecto"}, 400

    if tipo == "register":
        datos = verif["data"]
        hashed_password = generate_password_hash(datos["contrasena"])
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO usuario (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, noDocumento, correo, telefono, contrasena, rol, tipoDocumento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (datos["primer_nombre"], datos["segundo_nombre"], datos["primer_apellido"], datos["segundo_apellido"], datos["noDocumento"], datos["correo"], datos["telefono"], hashed_password, datos["rol"], datos["tipoDocumento"])
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            error_msg = str(e)
            if "Duplicate entry" in error_msg and "'correo'" in error_msg:
                return {"error": "El correo ya está registrado."}, 400
            if "Duplicate entry" in error_msg and "'noDocumento'" in error_msg:
                return {"error": "El documento ya está registrado."}, 400
            return {"error": error_msg}, 400
        finally:
            # consultar el usuario recién creado
            cursor.execute("SELECT * FROM usuario WHERE correo=%s", (datos["correo"],))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
        verification_codes.pop(correo)
        if user:
            # Consultar con columnas explícitas para enviar todos los campos necesarios
            user_data = get_user_by_correo(datos["correo"]) or {
                "id": user[0],
                "primer_nombre": user[1],
                "segundo_nombre": user[2],
                "primer_apellido": user[3],
                "segundo_apellido": user[4],
                "correo": user[7],
                "rol": user[10]
            }
            token = generate_token(user_data)
            return ({**user_data, "token": token}, 201)
        return {"message": "Usuario registrado exitosamente."}, 201

    elif tipo == "login":
        # Ignorar el usuario mínimo guardado y obtener datos completos desde DB
        user_data = get_user_by_correo(correo)
        verification_codes.pop(correo)
        if not user_data:
            return {"error": "Usuario no encontrado"}, 404
        token = generate_token(user_data)
        return jsonify({**user_data, "token": token}), 200

    return {"error": "Tipo de verificación inválido"}, 400

@app.route("/api/resend-code", methods=["POST"])
def resend_code():
    data = request.json
    correo = data.get("correo")
    tipo = data.get("tipo")
    
    print(f"🔧 Resend-code request: correo={correo}, tipo={tipo}")
    print(f"🔧 verification_codes keys: {list(verification_codes.keys())}")
    print(f"🔧 reset_codes keys: {list(reset_codes.keys())}")

    if not correo or not tipo:
        return {"error": "Correo y tipo son obligatorios"}, 400

    if tipo == "register":
        # Verificar si existe un código pendiente de registro
        print(f"🔧 Checking register for {correo}: {correo in verification_codes}")
        if correo in verification_codes and "data" in verification_codes[correo]:
            codigo = str(random.randint(100000, 999999))
            verification_codes[correo]["code"] = codigo
            print(f"🔧 Nuevo código de registro generado: {codigo}")
            email_sent = enviarCorreo(correo, codigo, async_send=False)
            if email_sent:
                return {"message": "Código reenviado correctamente"}, 200
            else:
                return {
                    "message": "Código generado correctamente.", 
                    "warning": "Hubo un problema enviando el correo. Usa el código: " + codigo
                }, 200
        else:
            print(f"🔧 No hay proceso de registro activo para {correo}")
            return {"error": "No hay proceso de registro pendiente para este correo"}, 400
            
    elif tipo == "login":
        # Verificar si existe un código pendiente de login
        print(f"🔧 Checking login for {correo}: {correo in verification_codes}")
        if correo in verification_codes and "user" in verification_codes[correo]:
            codigo = str(random.randint(100000, 999999))
            verification_codes[correo]["code"] = codigo
            print(f"🔧 Nuevo código de login generado: {codigo}")
            email_sent = enviarCorreo(correo, codigo, async_send=False)
            if email_sent:
                return {"message": "Código reenviado correctamente"}, 200
            else:
                return {
                    "message": "Código generado correctamente.", 
                    "warning": "Hubo un problema enviando el correo. Usa el código: " + codigo
                }, 200
        else:
            print(f"🔧 No hay proceso de login activo para {correo}")
            return {"error": "No hay proceso de login pendiente para este correo"}, 400
            
    elif tipo == "reset":
        # Verificar si existe un código pendiente de reset
        print(f"🔧 Checking reset for {correo}: {correo in reset_codes}")
        if correo in reset_codes:
            codigo = str(random.randint(100000, 999999))
            reset_codes[correo] = codigo
            print(f"🔧 Nuevo código de reset generado: {codigo}")
            email_sent = enviarCorreo(correo, codigo, async_send=False)
            if email_sent:
                return {"message": "Código reenviado correctamente"}, 200
            else:
                return {
                    "message": "Código generado correctamente.", 
                    "warning": "Hubo un problema enviando el correo. Usa el código: " + codigo
                }, 200
        else:
            # Si no existe en reset_codes, crear uno nuevo
            print(f"🔧 No hay proceso de reset activo, creando uno nuevo")
            codigo = str(random.randint(100000, 999999))
            reset_codes[correo] = codigo
            print(f"🔧 Nuevo código de reset creado: {codigo}")
            email_sent = enviarCorreo(correo, codigo, async_send=False)
            if email_sent:
                return {"message": "Código reenviado correctamente"}, 200
            else:
                return {
                    "message": "Código generado correctamente.", 
                    "warning": "Hubo un problema enviando el correo. Usa el código: " + codigo
                }, 200

    return {"error": "Tipo de reenvío inválido"}, 400

@app.route("/api/google-login", methods=["POST"])
def google_login():
    token = request.json.get("token")
    if not token:
        return {"error": "Token requerido"}, 400
    try:
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), os.getenv("GOOGLE_CLIENT_ID"))
        correo = idinfo["email"]
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuario WHERE correo=%s", (correo,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if not user:
            return {"error": "No existe usuario con ese correo"}, 404
        # Devolver datos completos (incluye telefono, noDocumento, tipoDocumento)
        user_data = get_user_by_correo(correo)
        if not user_data:
            # Fallback mínimo
            user_data = {
                "id": user[0],
                "primer_nombre": user[1],
                "segundo_nombre": user[2],
                "primer_apellido": user[3],
                "segundo_apellido": user[4],
                "correo": user[7],
                "rol": user[10]
            }
        token = generate_token(user_data)
        return {"user": {**user_data, "token": token}}, 200
    except Exception as e:
        msg = str(e)
        # Mensaje más amigable cuando el token indica diferencia de hora
        if "Token used too early" in msg or "token used too early" in msg:
            return {
                "error": "Token inválido: la hora del sistema parece estar desincronizada. "
                         "Sincroniza el reloj del equipo (NTP) y vuelve a intentarlo. "
                         "Ejemplo en Windows: Ajustes > Hora e idioma > Sincronizar ahora, o ejecutar 'w32tm /resync' en PowerShell con permisos de administrador.",
                "detalle": msg
            }, 400
        return {"error": msg}, 400

@app.route("/api/usuarios/<int:usuario_id>/foto", methods=["PUT"])
@token_required
def actualizar_foto_usuario(usuario_id):
    """Sube y actualiza la foto de perfil del usuario.
    Espera multipart/form-data con campo 'foto'. Devuelve { foto: "/uploads/images/profiles/<file>" }
    """
    if "foto" not in request.files:
        return {"error": "Archivo 'foto' es requerido"}, 400
    foto = request.files["foto"]
    if not foto.filename:
        return {"error": "Nombre de archivo inválido"}, 400
    filename = secure_filename(foto.filename)
    ext = os.path.splitext(filename)[1]
    unique_name = f"pf_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
    save_path = os.path.join(PROFILE_FOLDER, unique_name)
    foto.save(save_path)
    foto_url = f"/uploads/images/profiles/{unique_name}"

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE usuario SET foto=%s WHERE id=%s", (foto_url, usuario_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()
    return {"foto": foto_url}, 200

@app.route("/api/usuarios/<int:usuario_id>/cambiar-contrasena", methods=["PUT"])
@token_required
def cambiar_contrasena_usuario(usuario_id):
    """Cambia la contraseña del usuario autenticado.
    Espera JSON con: { actual: string, nueva: string }
    """
    data = request.json
    contrasena_actual = data.get("actual")
    contrasena_nueva = data.get("nueva")
    
    if not all([contrasena_actual, contrasena_nueva]):
        return {"error": "Contraseña actual y nueva son requeridas"}, 400
    
    if len(contrasena_nueva) < 6:
        return {"error": "La nueva contraseña debe tener al menos 6 caracteres"}, 400
    
    # Verificar que el usuario autenticado coincida
    if request.current_user["id"] != usuario_id:
        return {"error": "No tienes permiso para cambiar esta contraseña"}, 403
    
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Obtener la contraseña hasheada actual
        cursor.execute("SELECT contrasena FROM usuario WHERE id=%s", (usuario_id,))
        user = cursor.fetchone()
        
        if not user:
            return {"error": "Usuario no encontrado"}, 404
        
        # Verificar que la contraseña actual sea correcta
        if not check_password_hash(user[0], contrasena_actual):
            return {"error": "Contraseña actual incorrecta"}, 400
        
        # Hashear y actualizar la nueva contraseña
        hashed_nueva = generate_password_hash(contrasena_nueva)
        cursor.execute("UPDATE usuario SET contrasena=%s WHERE id=%s", (hashed_nueva, usuario_id))
        conn.commit()
        
        # Enviar correo de notificación
        cursor.execute("SELECT correo FROM usuario WHERE id=%s", (usuario_id,))
        correo_user = cursor.fetchone()
        if correo_user:
            enviarCorreoCambio(correo_user[0], async_send=False)
        
        return {"message": "Contraseña actualizada exitosamente"}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/google-register", methods=["POST"])
def google_register():
    token = request.json.get("token")
    rol = request.json.get("rol", "cliente")
    if not token:
        return {"error": "Token requerido"}, 400
    try:
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), os.getenv("GOOGLE_CLIENT_ID"))
        nombre_completo = idinfo.get("name", "")
        # Separar el nombre completo de Google
        partes_nombre = nombre_completo.split()
        primer_nombre = partes_nombre[0] if len(partes_nombre) > 0 else ""
        segundo_nombre = ""
        primer_apellido = partes_nombre[1] if len(partes_nombre) > 1 else ""
        segundo_apellido = ""
        
        # Si hay más de 2 partes, ajustar la distribución
        if len(partes_nombre) > 2:
            if len(partes_nombre) == 3:
                segundo_nombre = partes_nombre[1]
                primer_apellido = partes_nombre[2]
            elif len(partes_nombre) >= 4:
                segundo_nombre = partes_nombre[1]
                primer_apellido = partes_nombre[2]
                segundo_apellido = partes_nombre[3]
        
        correo = idinfo["email"]
        noDocumento = None
        telefono = None
        contrasena = os.urandom(16).hex()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuario WHERE correo=%s", (correo,))
        user = cursor.fetchone()
        if user:
            cursor.close()
            conn.close()
            return {"error": "El correo ya está registrado."}, 400
        hashed_password = generate_password_hash(contrasena)
        cursor.execute(
            "INSERT INTO usuario (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, noDocumento, correo, telefono, contrasena, rol) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, noDocumento, correo, telefono, hashed_password, rol)
        )
        conn.commit()
        cursor.execute("SELECT * FROM usuario WHERE correo=%s", (correo,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        # Devolver datos completos
        user_data = get_user_by_correo(correo)
        if not user_data and user:
            user_data = {
                "id": user[0],
                "primer_nombre": user[1],
                "segundo_nombre": user[2],
                "primer_apellido": user[3],
                "segundo_apellido": user[4],
                "correo": user[7],
                "rol": user[10]
            }
        token = generate_token(user_data)
        return {"user": {**user_data, "token": token}}, 201
    except Exception as e:
        msg = str(e)
        if "Token used too early" in msg or "token used too early" in msg:
            return {
                "error": "Token inválido: la hora del sistema parece estar desincronizada. "
                         "Sincroniza el reloj del equipo (NTP) y vuelve a intentarlo. "
                         "Ejemplo en Windows: Ajustes > Hora e idioma > Sincronizar ahora, o ejecutar 'w32tm /resync' en PowerShell con permisos de administrador.",
                "detalle": msg
            }, 400
        return {"error": msg}, 400

@app.route("/api/vehiculos", methods=["POST"])
@role_required(["camionero"])
def registrar_vehiculo():
    camionero_id = request.form.get("camionero_id")
    tipo_vehiculo = request.form.get("tipo_vehiculo")
    placa = request.form.get("placa")
    modelo = request.form.get("modelo")
    ano_modelo = request.form.get("ano_modelo")
    tarifa_diaria = request.form.get("tarifa_diaria")
    imagen_url = None
    tarjeta_propiedad_url = None
    soat_url = None
    revision_tecnomecanica_url = None

    imagen = request.files.get("imagen")
    if imagen:
        filename = secure_filename(imagen.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        imagen.save(os.path.join(IMAGES_FOLDER, unique_name))
        imagen_url = f"/uploads/images/{unique_name}" 

    # Guardar documentos del vehículo
    tarjeta_propiedad = request.files.get("tarjeta_propiedad")
    if tarjeta_propiedad:
        filename = secure_filename(tarjeta_propiedad.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        tarjeta_propiedad.save(os.path.join(DOCS_FOLDER, unique_name))
        tarjeta_propiedad_url = f"/uploads/docs/{unique_name}"

    soat = request.files.get("soat")
    if soat:
        filename = secure_filename(soat.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        soat.save(os.path.join(DOCS_FOLDER, unique_name))
        soat_url = f"/uploads/docs/{unique_name}"

    revision_tecnomecanica = request.files.get("revision_tecnomecanica")
    if revision_tecnomecanica:
        filename = secure_filename(revision_tecnomecanica.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        revision_tecnomecanica.save(os.path.join(DOCS_FOLDER, unique_name))
        revision_tecnomecanica_url = f"/uploads/docs/{unique_name}"

    if not all([camionero_id, tipo_vehiculo, placa, modelo, ano_modelo, tarifa_diaria]):
        return {"error": "Todos los campos son obligatorios."}, 400

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO vehiculo (camionero_id, tipo_vehiculo, placa, modelo, ano_modelo, imagen_url, tarifa_diaria, 
                                  tarjeta_propiedad, soat, revision_tecnomecanica, estado_aprobacion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pendiente')
            """,
            (camionero_id, tipo_vehiculo, placa, modelo, ano_modelo, imagen_url, tarifa_diaria,
             tarjeta_propiedad_url, soat_url, revision_tecnomecanica_url)
        )
        conn.commit()
        return {"message": "Vehículo registrado correctamente. Pendiente de aprobación."}, 201
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/vehiculos", methods=["GET"])
def listar_vehiculos():
    camionero_id = request.args.get("camionero_id")
    conn = get_connection()
    cursor = conn.cursor()
    if camionero_id:
        cursor.execute(
            """
            SELECT v.id, v.camionero_id, v.tipo_vehiculo, v.placa, v.modelo, v.ano_modelo, v.imagen_url, v.tarifa_diaria,
                   u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido, u.correo, u.telefono,
                   v.tarjeta_propiedad, v.soat, v.revision_tecnomecanica, v.estado_aprobacion
            FROM vehiculo v
            JOIN usuario u ON v.camionero_id = u.id
            WHERE v.camionero_id=%s
            """,
            (camionero_id,)
        )
    else:
        # Para clientes solo mostrar vehículos aprobados
        cursor.execute(
            """
            SELECT v.id, v.camionero_id, v.tipo_vehiculo, v.placa, v.modelo, v.ano_modelo, v.imagen_url, v.tarifa_diaria,
                   u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido, u.correo, u.telefono,
                   v.tarjeta_propiedad, v.soat, v.revision_tecnomecanica, v.estado_aprobacion
            FROM vehiculo v
            JOIN usuario u ON v.camionero_id = u.id
            WHERE v.estado_aprobacion = 'aprobado'
            """
        )
    vehiculos = cursor.fetchall()
    lista = []
    for v in vehiculos:
        vehiculo_id = v[0]
        cursor.execute(
            "SELECT AVG(estrellas) FROM calificacion_vehiculo WHERE vehiculo_destino_id=%s", (vehiculo_id,)
        )
        calificacion = cursor.fetchone()[0]
        lista.append({
            "id": v[0],
            "camionero_id": v[1],  # Incluir explícitamente el camionero_id
            "tipo_vehiculo": v[2],
            "placa": v[3],
            "modelo": v[4],
            "ano_modelo": v[5],
            "imagen_url": v[6],
            "tarifa_diaria": float(v[7]),
            "calificacion": calificacion,
            "conductor": {
                "id": v[1],  # También incluir el id en el objeto conductor
                "primer_nombre": v[8],
                "segundo_nombre": v[9],
                "primer_apellido": v[10],
                "segundo_apellido": v[11],
                "correo": v[12],
                "telefono": v[13]
            },
            "tarjeta_propiedad": v[14],
            "soat": v[15],
            "revision_tecnomecanica": v[16],
            "estado_aprobacion": v[17]
        })
    cursor.close()
    conn.close()
    return {"vehiculos": lista}, 200

@app.route("/api/vehiculos/<int:vehiculo_id>", methods=["PUT"])
def editar_vehiculo(vehiculo_id):
    camionero_id = request.form.get("camionero_id")
    tipo_vehiculo = request.form.get("tipo_vehiculo")
    placa = request.form.get("placa")
    modelo = request.form.get("modelo")
    ano_modelo = request.form.get("ano_modelo")
    tarifa_diaria = request.form.get("tarifa_diaria")
    imagen_url = None
    tarjeta_propiedad_url = None
    soat_url = None
    revision_tecnomecanica_url = None

    imagen = request.files.get("imagen")
    if imagen:
        filename = secure_filename(imagen.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        imagen.save(os.path.join(IMAGES_FOLDER, unique_name))
        imagen_url = f"/uploads/images/{unique_name}"

    # Manejar documentos del vehículo
    tarjeta_propiedad = request.files.get("tarjeta_propiedad")
    if tarjeta_propiedad:
        filename = secure_filename(tarjeta_propiedad.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        tarjeta_propiedad.save(os.path.join(DOCS_FOLDER, unique_name))
        tarjeta_propiedad_url = f"/uploads/docs/{unique_name}"

    soat = request.files.get("soat")
    if soat:
        filename = secure_filename(soat.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        soat.save(os.path.join(DOCS_FOLDER, unique_name))
        soat_url = f"/uploads/docs/{unique_name}"

    revision_tecnomecanica = request.files.get("revision_tecnomecanica")
    if revision_tecnomecanica:
        filename = secure_filename(revision_tecnomecanica.filename)
        ext = os.path.splitext(filename)[1]
        unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}{ext}"
        revision_tecnomecanica.save(os.path.join(DOCS_FOLDER, unique_name))
        revision_tecnomecanica_url = f"/uploads/docs/{unique_name}"

    if not all([camionero_id, tipo_vehiculo, placa, modelo, ano_modelo, tarifa_diaria]):
        return {"error": "Todos los campos son obligatorios."}, 400

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Construir query dinámicamente según archivos que se hayan subido
        updates = []
        params = []
        
        updates.extend(["camionero_id=%s", "tipo_vehiculo=%s", "placa=%s", "modelo=%s", "ano_modelo=%s", "tarifa_diaria=%s"])
        params.extend([camionero_id, tipo_vehiculo, placa, modelo, ano_modelo, tarifa_diaria])
        
        if imagen_url:
            updates.append("imagen_url=%s")
            params.append(imagen_url)
        
        if tarjeta_propiedad_url:
            updates.append("tarjeta_propiedad=%s")
            params.append(tarjeta_propiedad_url)
        
        if soat_url:
            updates.append("soat=%s")
            params.append(soat_url)
        
        if revision_tecnomecanica_url:
            updates.append("revision_tecnomecanica=%s")
            params.append(revision_tecnomecanica_url)
        
        params.append(vehiculo_id)
        
        query = f"UPDATE vehiculo SET {', '.join(updates)} WHERE id=%s"
        cursor.execute(query, tuple(params))
        conn.commit()
        return {"message": "Vehículo actualizado correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/vehiculos/<int:vehiculo_id>", methods=["DELETE"])
def eliminar_vehiculo(vehiculo_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM vehiculo WHERE id=%s", (vehiculo_id,))
        conn.commit()
        return {"message": "Vehículo eliminado correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/vehiculos-pendientes", methods=["GET"])
def listar_vehiculos_pendientes():
    """Endpoint para que el admin vea vehículos pendientes de aprobación"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT v.id, v.camionero_id, v.tipo_vehiculo, v.placa, v.modelo, v.ano_modelo, 
                   v.imagen_url, v.tarifa_diaria, v.tarjeta_propiedad, v.soat, v.revision_tecnomecanica,
                   v.estado_aprobacion,
                   u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido, 
                   u.correo, u.telefono
            FROM vehiculo v
            JOIN usuario u ON v.camionero_id = u.id
                        WHERE v.estado_aprobacion = 'pendiente'
                            AND v.tarjeta_propiedad IS NOT NULL AND v.tarjeta_propiedad <> ''
                            AND v.soat IS NOT NULL AND v.soat <> ''
                            AND v.revision_tecnomecanica IS NOT NULL AND v.revision_tecnomecanica <> ''
            ORDER BY v.id DESC
            """
        )
        vehiculos = cursor.fetchall()
        lista = []
        for v in vehiculos:
            lista.append({
                "id": v[0],
                "camionero_id": v[1],
                "tipo_vehiculo": v[2],
                "placa": v[3],
                "modelo": v[4],
                "ano_modelo": v[5],
                "imagen_url": v[6],
                "tarifa_diaria": float(v[7]),
                "tarjeta_propiedad": v[8],
                "soat": v[9],
                "revision_tecnomecanica": v[10],
                "estado_aprobacion": v[11],
                "conductor": {
                    "id": v[1],
                    "primer_nombre": v[12],
                    "segundo_nombre": v[13],
                    "primer_apellido": v[14],
                    "segundo_apellido": v[15],
                    "correo": v[16],
                    "telefono": v[17]
                }
            })
        return {"vehiculos": lista}, 200
    except Exception as e:
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/vehiculos/<int:vehiculo_id>/aprobar", methods=["PUT"])
@role_required(["admin"])
def aprobar_vehiculo(vehiculo_id):
    """Endpoint para que el admin apruebe un vehículo"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Validar que existan los 3 documentos antes de aprobar
        cursor.execute(
            """
            SELECT tarjeta_propiedad, soat, revision_tecnomecanica
            FROM vehiculo
            WHERE id=%s
            """,
            (vehiculo_id,)
        )
        doc = cursor.fetchone()
        if not doc:
            return {"error": "Vehículo no encontrado"}, 404
        tarjeta, soat, rev = doc
        if not tarjeta or tarjeta == '' or not soat or soat == '' or not rev or rev == '':
            return {"error": "No se puede aprobar: faltan documentos obligatorios."}, 400

        cursor.execute(
            "UPDATE vehiculo SET estado_aprobacion='aprobado' WHERE id=%s",
            (vehiculo_id,)
        )
        conn.commit()
        return {"message": "Vehículo aprobado correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/vehiculos/<int:vehiculo_id>/denegar", methods=["PUT"])
@role_required(["admin"])
def denegar_vehiculo(vehiculo_id):
    """Endpoint para que el admin deniegue un vehículo"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE vehiculo SET estado_aprobacion='denegado' WHERE id=%s",
            (vehiculo_id,)
        )
        conn.commit()
        return {"message": "Vehículo denegado."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/debug-reserva", methods=["POST"])
def debug_reserva():
    data = request.json
    cliente_id = data.get("cliente_id")
    vehiculo_id = data.get("vehiculo_id")
    fecha_inicio = data.get("fecha_inicio")
    fecha_fin = data.get("fecha_fin")
    direccion_inicio = data.get("direccion_inicio")
    direccion_destino = data.get("direccion_destino")
    total_pago = data.get("total_pago")
    if not all([cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino]):
        return {"error": "Todos los campos son obligatorios."}, 400

    fecha_inicio = redondear_hora(fecha_inicio)
    fecha_fin = redondear_hora(fecha_fin)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM reserva
            WHERE vehiculo_id=%s AND (
                (fecha_inicio <= %s AND fecha_fin >= %s) OR
                (fecha_inicio <= %s AND fecha_fin >= %s) OR
                (fecha_inicio >= %s AND fecha_fin <= %s)
            ) AND estado_reserva='activa'
        """, (vehiculo_id, fecha_inicio, fecha_inicio, fecha_fin, fecha_fin, fecha_inicio, fecha_fin))
        if cursor.fetchone()[0] > 0:
            return {"error": "El vehículo no está disponible en ese rango de fechas."}, 400

        cursor.execute("""
            INSERT INTO reserva (cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, total_pago)
            VALUES (%s, %s, %s, %s, %s, %s, 'activa', %s)
        """, (cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, total_pago))
        conn.commit()

        cursor.execute("""
            SELECT u.primer_nombre, u.primer_apellido, u.correo FROM usuario u
            JOIN vehiculo v ON v.camionero_id = u.id
            WHERE v.id=%s
        """, (vehiculo_id,))
        conductor = cursor.fetchone()
        cursor.execute("SELECT primer_nombre, primer_apellido, correo FROM usuario WHERE id=%s", (cliente_id,))
        cliente = cursor.fetchone()
        if conductor and cliente:
            mensaje_conductor = (
                f"Hola {conductor[0]},\n\n"
                f"{cliente[0]} te hizo una reserva para el vehículo {vehiculo_id} "
                f"del {fecha_inicio} al {fecha_fin}.\n"
                f"Dirección de inicio: {direccion_inicio}\n"
                f"Dirección de destino: {direccion_destino}\n\n"
                "Por favor, revisa tu panel para más detalles."
            )
            enviarCorreoReserva(conductor[2], mensaje_conductor, async_send=False)

            mensaje_cliente = (
                f"Hola {cliente[0]},\n\n"
                f"Tu reserva para el vehículo {vehiculo_id} fue realizada exitosamente.\n"
                f"Del {fecha_inicio} al {fecha_fin}.\n"
                f"Dirección de inicio: {direccion_inicio}\n"
                f"Dirección de destino: {direccion_destino}\n\n"
                f"El conductor es: {conductor[0]}, correo: {conductor[2]}.\n"
                "¡Gracias por usar PackyGo!"
            )
            enviarCorreoReserva(cliente[2], mensaje_cliente, async_send=False)
        return {"message": "Reserva realizada y correos enviados (debug)."}, 201
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reservas", methods=["POST"])
@role_required(["cliente"])
def crear_reserva():
    data = request.json
    cliente_id = data.get("cliente_id")
    vehiculo_id = data.get("vehiculo_id")
    fecha_inicio = data.get("fecha_inicio")
    fecha_fin = data.get("fecha_fin")
    direccion_inicio = data.get("direccion_inicio")
    direccion_destino = data.get("direccion_destino")
    total_pago = data.get("total_pago")
    if not all([cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino]):
        return {"error": "Todos los campos son obligatorios."}, 400

    fecha_inicio = redondear_hora(fecha_inicio)
    fecha_fin = redondear_hora(fecha_fin)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM reserva
            WHERE vehiculo_id=%s AND (
                (fecha_inicio <= %s AND fecha_fin >= %s) OR
                (fecha_inicio <= %s AND fecha_fin >= %s) OR
                (fecha_inicio >= %s AND fecha_fin <= %s)
            ) AND estado_reserva='activa'
        """, (vehiculo_id, fecha_inicio, fecha_inicio, fecha_fin, fecha_fin, fecha_inicio, fecha_fin))
        if cursor.fetchone()[0] > 0:
            return {"error": "El vehículo no está disponible en ese rango de fechas."}, 400

        cursor.execute("""
            INSERT INTO reserva (cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, total_pago)
            VALUES (%s, %s, %s, %s, %s, %s, 'activa', %s)
        """, (cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, total_pago))
        conn.commit()
        return {"message": "Reserva realizada correctamente."}, 201
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reservas", methods=["GET"])
def listar_reservas():
    vehiculo_id = request.args.get("vehiculo_id")
    cliente_id = request.args.get("cliente_id")  
    conn = get_connection()
    cursor = conn.cursor()
    if vehiculo_id:
        cursor.execute(
            """
            SELECT id, cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, total_pago
            FROM reserva
            WHERE vehiculo_id=%s AND estado_reserva='activa'
            """,
            (vehiculo_id,)
        )
    elif cliente_id:
        cursor.execute(
            """
            SELECT id, cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, total_pago
            FROM reserva
            WHERE cliente_id=%s
            ORDER BY fecha_inicio DESC
            """,
            (cliente_id,)
        )
    else:
        cursor.execute(
            """
            SELECT id, cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, total_pago
            FROM reserva
            WHERE estado_reserva='activa'
            """
        )
    reservas = cursor.fetchall()
    lista = []
    for r in reservas:
        lista.append({
            "id": r[0],
            "cliente_id": r[1],
            "vehiculo_id": r[2],
            "fecha_inicio": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            "fecha_fin": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
            "direccion_inicio": r[5],
            "direccion_destino": r[6],
            "estado_reserva": r[7],
            "total_pago": float(r[8]) if r[8] is not None else None
        })
    cursor.close()
    conn.close()
    return jsonify(reservas=lista), 200



@app.route("/api/reservas-todas", methods=["GET"])
def listar_todas_reservas():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, total_pago
        FROM reserva
        ORDER BY fecha_inicio DESC
        """
    )
    reservas = cursor.fetchall()
    lista = []
    for r in reservas:
        lista.append({
            "id": r[0],
            "cliente_id": r[1],
            "vehiculo_id": r[2],
            "fecha_inicio": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            "fecha_fin": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
            "direccion_inicio": r[5],
            "direccion_destino": r[6],
            "estado_reserva": r[7],
            "total_pago": float(r[8]) if r[8] is not None else None
        })
    cursor.close()
    conn.close()
    return {"reservas": lista}, 200

@app.route("/api/reservas/<int:reserva_id>/cancelar", methods=["PUT"])
def cancelar_reserva(reserva_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT cliente_id, vehiculo_id, fecha_inicio, fecha_fin FROM reserva WHERE id=%s", (reserva_id,)
        )
        reserva = cursor.fetchone()
        if not reserva:
            return {"error": "Reserva no encontrada."}, 404
        cliente_id, vehiculo_id, fecha_inicio, fecha_fin = reserva

        cursor.execute("SELECT primer_nombre, primer_apellido, correo FROM usuario WHERE id=%s", (cliente_id,))
        cliente = cursor.fetchone()

        cursor.execute("""
            SELECT u.primer_nombre, u.primer_apellido, u.correo FROM usuario u
            JOIN vehiculo v ON v.camionero_id = u.id
            WHERE v.id=%s
        """, (vehiculo_id,))
        conductor = cursor.fetchone()

        cursor.execute(
            "UPDATE reserva SET estado_reserva='cancelada' WHERE id=%s", (reserva_id,)
        )
        conn.commit()

        if cliente:
            mensaje_cliente = (
                f"Tu reserva del {fecha_inicio} al {fecha_fin} ha sido cancelada."
            )
            enviarCorreoCancelacion(cliente[1], cliente[0], mensaje_cliente, es_cliente=True, async_send=False)
        if conductor:
            mensaje_conductor = (
                f"Una reserva de tu vehículo del {fecha_inicio} al {fecha_fin} ha sido cancelada."
            )
            enviarCorreoCancelacion(conductor[1], conductor[0], mensaje_conductor, es_cliente=False, async_send=False)

        return {"message": "Reserva cancelada correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reservas/<int:reserva_id>/finalizar", methods=["PUT"])
def finalizar_reserva(reserva_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE reserva SET estado_reserva='finalizada' WHERE id=%s", (reserva_id,)
        )
        conn.commit()
        return {"message": "Reserva finalizada correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/pedidos-camionero/<int:camionero_id>", methods=["GET"])
def pedidos_camionero(camionero_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(""" 
            SELECT r.id, r.cliente_id, r.vehiculo_id, r.fecha_inicio, r.fecha_fin, r.direccion_inicio, r.direccion_destino, r.estado_reserva, r.total_pago,
                   v.tipo_vehiculo, v.placa, v.modelo, v.ano_modelo, v.imagen_url, v.tarifa_diaria,
                   u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido, u.correo, u.telefono
            FROM reserva r
            JOIN vehiculo v ON r.vehiculo_id = v.id
            JOIN usuario u ON r.cliente_id = u.id
            WHERE v.camionero_id = %s
            ORDER BY r.fecha_inicio DESC
        """, (camionero_id,))
        pedidos = []
        for row in cursor.fetchall():
            reserva = {
                "id": row[0],
                "cliente_id": row[1],
                "vehiculo_id": row[2],
                "fecha_inicio": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                "fecha_fin": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                "direccion_inicio": row[5],
                "direccion_destino": row[6],
                "estado_reserva": row[7],
                "total_pago": float(row[8]) if row[8] is not None else None
            }
            vehiculo = {
                "id": row[2],
                "tipo_vehiculo": row[9],
                "placa": row[10],
                "modelo": row[11],
                "ano_modelo": row[12],
                "imagen_url": row[13],
                "tarifa_diaria": float(row[14])
            }
            cliente = {
                "id": row[1],
                "primer_nombre": row[15],
                "segundo_nombre": row[16],
                "primer_apellido": row[17],
                "segundo_apellido": row[18],
                "correo": row[19],
                "telefono": row[20]
            }
            cursor.execute(
                "SELECT AVG(estrellas) FROM calificacion_usuario WHERE usuario_destino_id=%s", (row[1],)
            )
            calif = cursor.fetchone()[0]
            cliente["calificacion"] = float(calif) if calif is not None else None
            pedidos.append({
                "reserva": reserva,
                "vehiculo": vehiculo,
                "cliente": cliente
            })
        return {"pedidos": pedidos}, 200
    except Exception as e:
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reservas-vehiculo-todas/<int:vehiculo_id>", methods=["GET"])
def reservas_vehiculo_todas(vehiculo_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva
        FROM reserva
        WHERE vehiculo_id=%s
        ORDER BY fecha_inicio DESC
        """,
        (vehiculo_id,)
    )
    reservas = cursor.fetchall()
    lista = []
    for r in reservas:
        lista.append({
            "id": r[0],
            "cliente_id": r[1],
            "vehiculo_id": r[2],
            "fecha_inicio": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            "fecha_fin": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
            "direccion_inicio": r[5],
            "direccion_destino": r[6],
            "estado_reserva": r[7]
        })
    cursor.close()
    conn.close()
    return jsonify(reservas=lista), 200

@app.route("/api/reservas-usuario/<int:usuario_id>", methods=["GET"])
def reservas_por_usuario(usuario_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, total_pago
        FROM reserva
        WHERE cliente_id=%s
        ORDER BY fecha_inicio DESC
        """,
        (usuario_id,)
    )
    reservas = cursor.fetchall()
    lista = []
    for r in reservas:
        lista.append({
            "id": r[0],
            "cliente_id": r[1],
            "vehiculo_id": r[2],
            "fecha_inicio": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            "fecha_fin": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
            "direccion_inicio": r[5],
            "direccion_destino": r[6],
            "estado_reserva": r[7],
            "total_pago": float(r[8]) if r[8] is not None else None
        })
    cursor.close()
    conn.close()
    return jsonify(reservas=lista), 200

@app.route("/api/calificar-cliente", methods=["POST"])
def calificar_cliente():
    data = request.json
    usuario_destino_id = data.get("usuario_destino_id")
    autor_id = data.get("usuario_origen_id")
    estrellas = data.get("estrellas")
    comentario = data.get("comentario", "")
    if not all([usuario_destino_id, autor_id, estrellas]):
        return {"error": "Datos incompletos"}, 400
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO calificacion_usuario (usuario_destino_id, autor_id, estrellas, comentario) VALUES (%s, %s, %s, %s)",
            (usuario_destino_id, autor_id, estrellas, comentario)
        )
        conn.commit()
        return {"message": "Calificación registrada"}, 201
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/calificaciones-vehiculo", methods=["GET"])
def calificaciones_vehiculo():
    autor_id = request.args.get("autor_id")
    vehiculo_id = request.args.get("vehiculo_id")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, reserva_id FROM calificacion_vehiculo WHERE autor_id=%s AND vehiculo_destino_id=%s",
        (autor_id, vehiculo_id)
    )
    calificaciones = cursor.fetchall()
    cursor.close()
    conn.close()
    return {"calificaciones": [{"id": c[0], "reserva_id": c[1]} for c in calificaciones]}, 200



@app.route("/api/calificaciones-vehiculo-todas", methods=["GET"])
def calificaciones_vehiculo_todas():
    vehiculo_id = request.args.get("vehiculo_id")
    conn = get_connection()
    cursor = conn.cursor()
    calificaciones = []
    if vehiculo_id:
        cursor.execute(
            "SELECT id, reserva_id, autor_id, vehiculo_destino_id, estrellas, comentario FROM calificacion_vehiculo WHERE vehiculo_destino_id=%s",
            (vehiculo_id,)
        )
        rows = cursor.fetchall()
        for row in rows:
            calificaciones.append({
                "id": row[0],
                "reserva_id": row[1],
                "autor_id": row[2],
                "vehiculo_destino_id": row[3],
                "estrellas": row[4],
                "comentario": row[5]
            })
    cursor.close()
    conn.close()
    return {"calificaciones": calificaciones}, 200

@app.route("/api/calificar-vehiculo", methods=["POST"])
def calificar_vehiculo():
    data = request.json
    autor_id = data.get("autor_id")
    vehiculo_destino_id = data.get("vehiculo_destino_id")
    reserva_id = data.get("reserva_id")
    estrellas = data.get("estrellas")
    comentario = data.get("comentario", "")
    if not all([autor_id, vehiculo_destino_id, reserva_id, estrellas]):
        return {"error": "Datos incompletos"}, 400
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO calificacion_vehiculo (autor_id, vehiculo_destino_id, reserva_id, estrellas, comentario) VALUES (%s, %s, %s, %s, %s)",
            (autor_id, vehiculo_destino_id, reserva_id, estrellas, comentario)
        )
        conn.commit()
        return {"message": "Calificación registrada"}, 201
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/api/usuarios", methods=["GET"])
def listar_usuarios():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, noDocumento, correo, telefono, rol, tipoDocumento FROM usuario")
    usuarios = cursor.fetchall()
    lista = []
    for u in usuarios:
        lista.append({
            "id": u[0],
            "primer_nombre": u[1],
            "segundo_nombre": u[2],
            "primer_apellido": u[3],
            "segundo_apellido": u[4],
            "noDocumento": u[5],
            "correo": u[6],
            "telefono": u[7],
            "rol": u[8],
            "tipoDocumento": u[9]
        })
    cursor.close()
    conn.close()
    return jsonify(usuarios=lista), 200

@app.route("/api/usuarios", methods=["POST"])
@role_required(["admin"])
def crear_usuario():
    data = request.json or {}
    primer_nombre = data.get("primer_nombre")
    segundo_nombre = data.get("segundo_nombre", "")
    primer_apellido = data.get("primer_apellido")
    segundo_apellido = data.get("segundo_apellido", "")
    noDocumento = data.get("noDocumento")
    tipoDocumento = data.get("tipoDocumento")
    correo = data.get("correo")
    telefono = data.get("telefono")
    rol = data.get("rol")
    contrasena = data.get("contrasena") or "123456"

    if not all([primer_nombre, primer_apellido, noDocumento, tipoDocumento, correo, telefono, rol]):
        return {"error": "Faltan datos obligatorios"}, 400

    conn = get_connection()
    cursor = conn.cursor()
    try:
        hashed = generate_password_hash(contrasena)
        cursor.execute(
            "INSERT INTO usuario (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, noDocumento, correo, telefono, rol, contrasena, tipoDocumento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, noDocumento, correo, telefono, rol, hashed, tipoDocumento)
        )
        conn.commit()
        return {"message": "Usuario creado"}, 201
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 400
    finally:
        cursor.close()
        conn.close()

@app.route("/api/usuarios/<int:usuario_id>", methods=["PUT"])
@role_required(["admin"])
def editar_usuario(usuario_id):
    data = request.json
    primer_nombre = data.get("primer_nombre")
    segundo_nombre = data.get("segundo_nombre", "")
    primer_apellido = data.get("primer_apellido")
    segundo_apellido = data.get("segundo_apellido", "")
    correo = data.get("correo")
    noDocumento = data.get("noDocumento")
    tipoDocumento = data.get("tipoDocumento")
    telefono = data.get("telefono")
    rol = data.get("rol")
    if not all([primer_nombre, primer_apellido, correo, noDocumento, tipoDocumento, telefono, rol]):
        return {"error": "Faltan datos obligatorios"}, 400
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE usuario SET primer_nombre=%s, segundo_nombre=%s, primer_apellido=%s, segundo_apellido=%s, correo=%s, noDocumento=%s, tipoDocumento=%s, telefono=%s, rol=%s WHERE id=%s",
            (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, correo, noDocumento, tipoDocumento, telefono, rol, usuario_id)
        )
        conn.commit()
        return {"message": "Usuario actualizado"}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 400
    finally:
        cursor.close()
        conn.close()


@app.route("/api/usuarios/<int:usuario_id>/perfil", methods=["PUT"])
@token_required
def editar_perfil_usuario(usuario_id):
    """
    Permite al usuario actualizar su propio perfil (o a un admin actualizar cualquier perfil).
    Campos permitidos: primer_nombre, segundo_nombre, primer_apellido, segundo_apellido,
    correo, noDocumento, tipoDocumento, telefono
    """
    # Verificar permisos: el usuario debe ser el mismo que solicita o ser admin
    current = getattr(request, 'current_user', None)
    if not current:
        return {"error": "No autorizado"}, 401
    if current.get('rol') != 'admin' and current.get('id') != usuario_id:
        return {"error": "No tienes permisos para editar este perfil"}, 403

    data = request.json or {}
    primer_nombre = data.get("primer_nombre")
    segundo_nombre = data.get("segundo_nombre", "")
    primer_apellido = data.get("primer_apellido")
    segundo_apellido = data.get("segundo_apellido", "")
    correo = data.get("correo")
    noDocumento = data.get("noDocumento")
    tipoDocumento = data.get("tipoDocumento")
    telefono = data.get("telefono")

    if not all([primer_nombre, primer_apellido, correo]):
        return {"error": "Faltan datos obligatorios"}, 400

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Verificar duplicados para correo/noDocumento (si cambian)
        cursor.execute("SELECT id FROM usuario WHERE correo=%s AND id<>%s", (correo, usuario_id))
        if cursor.fetchone():
            return {"error": "El correo ya está registrado."}, 400
        if noDocumento:
            cursor.execute("SELECT id FROM usuario WHERE noDocumento=%s AND id<>%s", (noDocumento, usuario_id))
            if cursor.fetchone():
                return {"error": "El documento ya está registrado."}, 400

        cursor.execute(
            "UPDATE usuario SET primer_nombre=%s, segundo_nombre=%s, primer_apellido=%s, segundo_apellido=%s, correo=%s, noDocumento=%s, tipoDocumento=%s, telefono=%s WHERE id=%s",
            (primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, correo, noDocumento, tipoDocumento, telefono, usuario_id)
        )
        conn.commit()
        # Devolver datos actualizados
        cursor.execute("SELECT id, primer_nombre, segundo_nombre, primer_apellido, segundo_apellido, tipoDocumento, noDocumento, correo, telefono, rol, fecha_registro, foto FROM usuario WHERE id=%s", (usuario_id,))
        row = cursor.fetchone()
        user_data = build_user_dict(row)
        return jsonify(user_data), 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 400
    finally:
        cursor.close()
        conn.close()

@app.route("/api/usuarios/<int:usuario_id>", methods=["DELETE"])
def eliminar_usuario(usuario_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM usuario WHERE id=%s", (usuario_id,))
        conn.commit()
        return {"message": "Usuario eliminado"}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 400
    finally:
        cursor.close()
        conn.close()

@app.route("/api/usuarios-detallado", methods=["GET"])
def usuarios_detallado():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido, u.noDocumento, u.correo, u.telefono, u.rol, u.tipoDocumento,
            COUNT(DISTINCT v.id) as vehiculos,
            COUNT(DISTINCT r.id) as reservas
        FROM usuario u
        LEFT JOIN vehiculo v ON v.camionero_id = u.id
        LEFT JOIN reserva r ON r.cliente_id = u.id
        GROUP BY u.id
    """)
    usuarios = cursor.fetchall()
    lista = []
    for u in usuarios:
        lista.append({
            "id": u[0],
            "primer_nombre": u[1],
            "segundo_nombre": u[2],
            "primer_apellido": u[3],
            "segundo_apellido": u[4],
            "noDocumento": u[5],
            "correo": u[6],
            "telefono": u[7],
            "rol": u[8],
            "tipoDocumento": u[9],
            "vehiculos": u[10],
            "reservas": u[11]
        })
    cursor.close()
    conn.close()
    return {"usuarios": lista}, 200

@app.route("/api/reservas/<int:reserva_id>", methods=["PUT"])
def editar_reserva(reserva_id):
    data = request.json
    cliente_id = data.get("cliente_id")
    vehiculo_id = data.get("vehiculo_id")
    fecha_inicio = data.get("fecha_inicio")
    fecha_fin = data.get("fecha_fin")
    direccion_inicio = data.get("direccion_inicio")
    direccion_destino = data.get("direccion_destino")
    estado_reserva = data.get("estado_reserva")
    if not all([cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva]):
        return {"error": "Todos los campos son obligatorios."}, 400

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE reserva SET cliente_id=%s, vehiculo_id=%s, fecha_inicio=%s, fecha_fin=%s,
            direccion_inicio=%s, direccion_destino=%s, estado_reserva=%s
            WHERE id=%s
        """, (cliente_id, vehiculo_id, fecha_inicio, fecha_fin, direccion_inicio, direccion_destino, estado_reserva, reserva_id))
        conn.commit()
        return {"message": "Reserva actualizada correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reservas/<int:reserva_id>", methods=["DELETE"])
def eliminar_reserva(reserva_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM reserva WHERE id=%s", (reserva_id,))
        conn.commit()
        return {"message": "Reserva eliminada correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reportes", methods=["POST"])
def crear_reporte():
    data = request.json
    reserva_id = data.get("reserva_id")
    usuario_id = data.get("usuario_id")
    descripcion = data.get("descripcion")
    estado_reporte = data.get("estado_reporte", "abierto")
    fecha_reporte = data.get("fecha_reporte", datetime.now())
    if not all([reserva_id, usuario_id, descripcion]):
        return {"error": "Todos los campos son obligatorios."}, 400

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO reporte (reserva_id, usuario_id, descripcion, estado_reporte, fecha_reporte)
            VALUES (%s, %s, %s, %s, %s)
        """, (reserva_id, usuario_id, descripcion, estado_reporte, fecha_reporte))
        conn.commit()
        return {"message": "Reporte creado correctamente."}, 201
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reportes", methods=["GET"])
def listar_reportes():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.reserva_id, r.usuario_id, u.primer_nombre, u.primer_apellido, r.descripcion, r.estado_reporte, r.fecha_reporte
        FROM reporte r
        JOIN usuario u ON r.usuario_id = u.id
        ORDER BY r.fecha_reporte DESC
    """)
    reportes = cursor.fetchall()
    lista = []
    for rep in reportes:
        lista.append({
            "id": rep[0],
            "reserva_id": rep[1],
            "usuario_id": rep[2],
            "usuario_nombre": f"{rep[3]} {rep[4]}".strip(),
            "descripcion": rep[5],
            "estado_reporte": rep[6],
            "fecha_reporte": rep[7].isoformat() if hasattr(rep[7], "isoformat") else str(rep[7])
        })
    cursor.close()
    conn.close()
    return {"reportes": lista}, 200

@app.route("/api/reportes/<int:reporte_id>", methods=["PUT"])
def editar_reporte(reporte_id):
    data = request.json
    reserva_id = data.get("reserva_id")
    usuario_id = data.get("usuario_id")
    descripcion = data.get("descripcion")
    estado_reporte = data.get("estado_reporte")
    fecha_reporte = data.get("fecha_reporte")
    if not all([reserva_id, usuario_id, descripcion, estado_reporte, fecha_reporte]):
        return {"error": "Todos los campos son obligatorios."}, 400

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE reporte SET reserva_id=%s, usuario_id=%s, descripcion=%s, estado_reporte=%s, fecha_reporte=%s
            WHERE id=%s
        """, (reserva_id, usuario_id, descripcion, estado_reporte, fecha_reporte, reporte_id))
        conn.commit()
        return {"message": "Reporte actualizado correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reportes/<int:reporte_id>", methods=["DELETE"])
def eliminar_reporte(reporte_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM reporte WHERE id=%s", (reporte_id,))
        conn.commit()
        return {"message": "Reporte eliminado correctamente."}, 200
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route("/api/reportes-detallado", methods=["GET"])
def reportes_detallado():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.descripcion, r.estado_reporte, r.fecha_reporte,
               u.id, u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido, u.correo,
               res.id, res.fecha_inicio, res.fecha_fin,
               v.id, v.placa
        FROM reporte r
        JOIN usuario u ON r.usuario_id = u.id
        JOIN reserva res ON r.reserva_id = res.id
        JOIN vehiculo v ON res.vehiculo_id = v.id
        ORDER BY r.fecha_reporte DESC
    """)
    reportes = cursor.fetchall()
    lista = []
    for rep in reportes:
        lista.append({
            "id": rep[0],
            "descripcion": rep[1],
            "estado_reporte": rep[2],
            "fecha_reporte": rep[3].isoformat() if hasattr(rep[3], "isoformat") else str(rep[3]),
            "usuario_id": rep[4],
            "usuario_nombre": f"{rep[5]} {rep[7]}".strip(),
            "usuario_correo": rep[9],
            "reserva_id": rep[10],
            "reserva_fecha_inicio": rep[11].isoformat() if hasattr(rep[11], "isoformat") else str(rep[11]),
            "reserva_fecha_fin": rep[12].isoformat() if hasattr(rep[12], "isoformat") else str(rep[12]),
            "vehiculo_id": rep[13],
            "vehiculo_placa": rep[14]
        })
    cursor.close()
    conn.close()
    return {"reportes": lista}, 200

@app.route("/api/reservas-detallado", methods=["GET"])
def reservas_detallado():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.fecha_inicio, r.fecha_fin, r.direccion_inicio, r.direccion_destino, r.estado_reserva,
               c.id, c.primer_nombre, c.segundo_nombre, c.primer_apellido, c.segundo_apellido, c.correo,
               v.id, v.tipo_vehiculo, v.placa,
               u.id, u.primer_nombre, u.primer_apellido,
               r.total_pago
        FROM reserva r
        JOIN usuario c ON r.cliente_id = c.id
        JOIN vehiculo v ON r.vehiculo_id = v.id
        JOIN usuario u ON v.camionero_id = u.id
        ORDER BY r.fecha_inicio DESC
    """)
    reservas = cursor.fetchall()
    lista = []
    for r in reservas:
        lista.append({
            "id": r[0],
            "fecha_inicio": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
            "fecha_fin": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
            "direccion_inicio": r[3],
            "direccion_destino": r[4],
            "estado_reserva": r[5],
            "cliente_id": r[6],
            "cliente_nombre": f"{r[7]} {r[9]}".strip(),
            "cliente_correo": r[11],
            "vehiculo_id": r[12],
            "vehiculo_tipo": r[13],
            "vehiculo_placa": r[14],
            "camionero_id": r[15],
            "camionero_nombre": f"{r[16]} {r[17]}".strip(),
            "total_pago": float(r[18]) if r[18] is not None else None
        })
    cursor.close()
    conn.close()
    return {"reservas": lista}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)