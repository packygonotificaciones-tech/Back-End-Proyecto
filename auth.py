import jwt
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "tu-clave-secreta-super-segura-cambiala-en-produccion")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 horas

def generate_token(user_data):
    """
    Genera un token JWT para el usuario
    user_data debe incluir: id, correo, rol
    """
    payload = {
        "id": user_data["id"],
        "correo": user_data["correo"],
        "rol": user_data["rol"],
        "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.utcnow()
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token

def verify_token(token):
    """
    Verifica y decodifica un token JWT
    Retorna el payload si es válido, None si no lo es
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def token_required(f):
    """
    Decorador para proteger rutas que requieren autenticación
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Obtener token del header Authorization
        if "Authorization" in request.headers:
            auth_header = request.headers["Authorization"]
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({"error": "Token malformado"}), 401
        
        if not token:
            return jsonify({"error": "Token no proporcionado"}), 401
        
        # Verificar token
        payload = verify_token(token)
        if not payload:
            return jsonify({"error": "Token inválido o expirado"}), 401
        
        # Pasar datos del usuario a la función
        request.current_user = payload
        return f(*args, **kwargs)
    
    return decorated

def role_required(allowed_roles):
    """
    Decorador para proteger rutas que requieren roles específicos
    allowed_roles: lista de roles permitidos, ej: ["admin", "camionero"]
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = None
            
            if "Authorization" in request.headers:
                auth_header = request.headers["Authorization"]
                try:
                    token = auth_header.split(" ")[1]
                except IndexError:
                    return jsonify({"error": "Token malformado"}), 401
            
            if not token:
                return jsonify({"error": "Token no proporcionado"}), 401
            
            payload = verify_token(token)
            if not payload:
                return jsonify({"error": "Token inválido o expirado"}), 401
            
            # Verificar rol
            user_role = payload.get("rol")
            if user_role not in allowed_roles:
                return jsonify({"error": "No tienes permisos para acceder a este recurso"}), 403
            
            request.current_user = payload
            return f(*args, **kwargs)
        
        return decorated
    return decorator
