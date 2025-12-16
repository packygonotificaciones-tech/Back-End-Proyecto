import os
from email.message import EmailMessage
import ssl
import smtplib
import threading
from dotenv import load_dotenv
from datetime import datetime
import sys
import traceback

load_dotenv()
email_sender = "packygonotificaciones@gmail.com"  
password = os.getenv("PASSWORD")
DEV_MODE = os.getenv("FLASK_DEBUG", "0") == "1"  

BRAND_PRIMARY = os.getenv("BRAND_PRIMARY", "#0097a7")
BRAND_SECONDARY = os.getenv("BRAND_SECONDARY", "#083c5d")
def _build_html_template(title: str, subtitle: str, body_html: str, primary_color: str = BRAND_PRIMARY, secondary_color: str = BRAND_SECONDARY) -> str:
        """Construye una plantilla HTML minimalista y moderna para los correos.

        Parámetros:
            - title, subtitle: títulos del correo
            - body_html: contenido principal
            - primary_color, secondary_color: colores de marca
        """
        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; background:#ffffff; padding:24px;">
            <div style="max-width:600px;margin:0 auto;">
                <div style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.05);">
                    <div style="padding:32px 36px;background:linear-gradient(135deg,{primary_color},{secondary_color});color:white;">
                        <h1 style="margin:0;font-size:24px;font-weight:700;">{title}</h1>
                        <div style="margin-top:8px;font-size:16px;opacity:0.92;">{subtitle}</div>
                    </div>

                    <div style="padding:36px;background:white;color:#2c3e50;font-size:16px;line-height:1.6;">
                        {body_html}
                    </div>

                    <div style="padding:24px 36px;background:#f8fafc;border-top:1px solid #edf2f7;color:#64748b;font-size:14px;text-align:center;">
                        PackyGo © {datetime.now().year}
                    </div>
                </div>
            </div>
        </div>
        """
        return html


def _send_email(to_email: str, subject: str, plain_text: str, html: str, async_send: bool = True):
  # Si no hay password y estamos en modo desarrollo, simular envío
  if not password:
    if DEV_MODE:
      print(f"🔧 MODO DESARROLLO - Simulando envío de correo a {to_email}:")
      print(f"   📧 Asunto: {subject}")
      print(f"   📝 Contenido: {plain_text}")
      print(f"   ✅ Correo 'enviado' exitosamente (modo desarrollo)")
      return True
    raise ValueError("PASSWORD no está configurado en las variables de entorno")

  def _send_sync():
    try:
      print(f"[{datetime.now().isoformat()}] 🔧 Iniciando envío síncrono a {to_email}", file=sys.stderr, flush=True)
      em = EmailMessage()
      em["From"] = email_sender
      em["To"] = to_email
      em["Subject"] = subject
      em.set_content(plain_text)
      em.add_alternative(html, subtype="html")

      print(f"[{datetime.now().isoformat()}] 🔧 Creando contexto SSL...", file=sys.stderr, flush=True)
      context = ssl.create_default_context()
      # Añadir timeout para evitar bloqueos prolongados
      print(f"[{datetime.now().isoformat()}] 🔧 Conectando a smtp.gmail.com:465 con timeout=15s...", file=sys.stderr, flush=True)
      with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=15) as smtp:
        print(f"[{datetime.now().isoformat()}] 🔧 Conectado. Autenticando como {email_sender}...", file=sys.stderr, flush=True)
        smtp.login(email_sender, password)
        print(f"[{datetime.now().isoformat()}] 🔧 Autenticación exitosa. Enviando mensaje...", file=sys.stderr, flush=True)
        smtp.send_message(em)
      print(f"[{datetime.now().isoformat()}] ✅ Correo '{subject}' enviado exitosamente a {to_email}", file=sys.stderr, flush=True)
      return True
    except smtplib.SMTPAuthenticationError as e:
      print(f"[{datetime.now().isoformat()}] ❌ Error de autenticación Gmail para {to_email}:", file=sys.stderr, flush=True)
      print(f"   - Verifica que la cuenta {email_sender} tenga 2FA habilitado", file=sys.stderr, flush=True)
      print(f"   - Genera una nueva contraseña de aplicación en: https://myaccount.google.com/apppasswords", file=sys.stderr, flush=True)
      print(f"   - Actualiza la variable PASSWORD en el archivo .env", file=sys.stderr, flush=True)
      print(f"   - Error técnico: {e}", file=sys.stderr, flush=True)
      traceback.print_exc(file=sys.stderr)
      if DEV_MODE:
        print(f"🔧 MODO DESARROLLO - Código disponible en consola:", file=sys.stderr, flush=True)
        print(f"   📝 {plain_text}", file=sys.stderr, flush=True)
      return False
    except Exception as e:
      print(f"[{datetime.now().isoformat()}] ❌ Error al enviar correo '{subject}' a {to_email}: {e}", file=sys.stderr, flush=True)
      traceback.print_exc(file=sys.stderr)
      if DEV_MODE:
        print(f"🔧 MODO DESARROLLO - Código disponible en consola:", file=sys.stderr, flush=True)
        print(f"   📝 {plain_text}", file=sys.stderr, flush=True)
      return False

  # Si se solicita envío síncrono, ejecutar y devolver el resultado
  if not async_send:
    print(f"🔧 Envío síncrono solicitado para {to_email}")
    return _send_sync()

  # Ejecutar envío en un hilo separado para no bloquear la petición HTTP
  thread = threading.Thread(target=_send_sync, daemon=True)
  thread.start()
  print(f"🔧 Correo encolado para envío a {to_email}")
  return True


def enviarCorreo(correo, codigoVerificacion, async_send=True):
    subject = "Código de verificación — PackyGo"
    plain = f"Tu código de verificación es: {codigoVerificacion}\n\nIngresa este código en la aplicación para continuar."
    body_html = f"""
      <div style="text-align:center;">
        <div style="margin:0 0 24px 0;color:#64748b;font-size:16px;">Este es tu código de verificación:</div>
        <div style="display:inline-block;padding:16px 32px;border-radius:12px;background:#f1f5f9;color:#0f172a;font-weight:700;font-size:28px;letter-spacing:8px;margin:0;">{codigoVerificacion}</div>
        <div style="margin:24px 0 0 0;color:#94a3b8;font-size:14px;">Ingresa este código en la aplicación para continuar</div>
      </div>
    """
    html = _build_html_template("Verificación de cuenta", "Código de verificación", body_html)
    return _send_email(correo, subject, plain, html, async_send=async_send)


def enviarCorreoCambio(correo, async_send=True):
    subject = "Tu contraseña fue actualizada — PackyGo"
    plain = "Tu contraseña ha sido cambiada exitosamente. Si no fuiste tú, contacta soporte de inmediato."
    body_html = """
      <div style="text-align:center;">
        <div style="margin:0 0 20px 0;">
          <span style="display:inline-block;width:48px;height:48px;background:#22c55e;border-radius:50%;margin-bottom:16px;">
            <span style="line-height:48px;font-size:24px;color:white;">✓</span>
          </span>
          <div style="color:#64748b;font-size:16px;">Tu contraseña ha sido actualizada correctamente</div>
        </div>
        <div style="color:#94a3b8;font-size:14px;">Si no reconoces este cambio, contacta a soporte de inmediato</div>
      </div>
    """
    html = _build_html_template("Contraseña actualizada", "Actualización de seguridad", body_html)
    return _send_email(correo, subject, plain, html, async_send=async_send)


def enviarCorreoVerificacion(correo, codigoVerificacion, async_send=True):
    subject = "Verifica tu correo — PackyGo"
    plain = f"Tu código de verificación es: {codigoVerificacion}\n\nUsa este código para confirmar tu cuenta en PackyGo."
    body_html = f"""
      <div style="text-align:center;">
        <div style="margin:0 0 24px 0;color:#64748b;font-size:16px;">Para completar tu registro, usa este código:</div>
        <div style="display:inline-block;padding:16px 32px;border-radius:12px;background:#f1f5f9;color:#0f172a;font-weight:700;font-size:28px;letter-spacing:8px;margin:0;">{codigoVerificacion}</div>
        <div style="margin:24px 0 0 0;color:#94a3b8;font-size:14px;">Ingresa este código en la aplicación para verificar tu cuenta</div>
      </div>
    """
    html = _build_html_template("Bienvenido a PackyGo", "Verificación de cuenta", body_html)
    return _send_email(correo, subject, plain, html, async_send=async_send)


def enviarCorreoReserva(correo, mensaje, async_send=True):
    subject = "Nueva reserva — PackyGo"
    plain = mensaje
    short_msg = f"{mensaje[:300]}..." if len(mensaje) > 300 else mensaje
    body_html = f"""
      <div style="text-align:center;">
        <span style="display:inline-block;width:64px;height:64px;background:#0097a7;border-radius:50%;margin-bottom:20px;">
          <span style="line-height:64px;font-size:32px;color:white;">🚚</span>
        </span>
        <h3 style="margin:0 0 16px 0;color:#0f172a;font-size:18px;">¡Tienes una nueva reserva!</h3>
        <p style="margin:0;color:#546e7a;font-size:15px;white-space:pre-line;text-align:left;">{short_msg}</p>
      </div>
    """
    html = _build_html_template("Nueva reserva recibida", "Tienes una nueva reserva", body_html)
    return _send_email(correo, subject, plain, html, async_send=async_send)


def enviarCorreoCancelacion(correo, nombre, mensaje_extra, es_cliente=True, async_send=True):
    subject = "Reserva cancelada — PackyGo"
    if es_cliente:
        texto = f"Hola {nombre}, tu reserva ha sido cancelada. {mensaje_extra}"
        subtitle = "Reserva cancelada"
    else:
        texto = f"Hola {nombre}, una reserva de tu vehículo ha sido cancelada. {mensaje_extra}"
        subtitle = "Reserva cancelada"

    plain = texto
    body_html = f"""
      <div style="text-align:center;">
        <span style="display:inline-block;width:64px;height:64px;background:#ef4444;border-radius:50%;margin-bottom:20px;">
          <span style="line-height:64px;font-size:32px;color:white;">✕</span>
        </span>
        <h3 style="margin:0 0 16px 0;color:#0f172a;font-size:18px;">Reserva Cancelada</h3>
        <p style="margin:0;color:#546e7a;font-size:15px;text-align:left;">{texto}</p>
      </div>
    """
    html = _build_html_template("Notificación de cancelación", subtitle, body_html)
    return _send_email(correo, subject, plain, html, async_send=async_send)