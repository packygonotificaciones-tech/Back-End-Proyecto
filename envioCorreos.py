import os
from email.message import EmailMessage
import ssl
import smtplib
import threading
import traceback
from dotenv import load_dotenv
from datetime import datetime

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


def _send_email(to_email: str, subject: str, plain_text: str, html: str):
  # Si no hay password y estamos en modo desarrollo, simular envío
  if not password:
    if DEV_MODE:
      print(f"🔧 MODO DESARROLLO - Simulando envío de correo a {to_email}:")
      print(f"   📧 Asunto: {subject}")
      print(f"   📝 Contenido: {plain_text}")
      print(f"   ✅ Correo 'enviado' exitosamente (modo desarrollo)")
      return True
    # Evitar levantar excepción que pueda interrumpir la petición HTTP.
    print(f"❌ PASSWORD no está configurado en las variables de entorno. No se enviará correo a {to_email}.")
    return False

  def _send_sync():
    try:
      em = EmailMessage()
      em["From"] = email_sender
      em["To"] = to_email
      em["Subject"] = subject
      em.set_content(plain_text)
      em.add_alternative(html, subtype="html")

      context = ssl.create_default_context()
      # Añadir timeout para evitar bloqueos prolongados
      with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=15) as smtp:
        smtp.login(email_sender, password)
        smtp.send_message(em)
      print(f"✅ Correo '{subject}' enviado exitosamente a {to_email}")
    except smtplib.SMTPAuthenticationError as e:
      print(f"❌ Error de autenticación Gmail para {to_email}:")
      print(f"   - Verifica que la cuenta {email_sender} tenga 2FA habilitado")
      print(f"   - Genera una nueva contraseña de aplicación en: https://myaccount.google.com/apppasswords")
      print(f"   - Actualiza la variable PASSWORD en el archivo .env")
      print(f"   - Error técnico: {e}")
      if DEV_MODE:
        print(f"🔧 MODO DESARROLLO - Código disponible en consola:")
        print(f"   📝 {plain_text}")
      traceback.print_exc()
    except Exception as e:
      print(f"❌ Error al enviar correo '{subject}' a {to_email}: {e}")
      traceback.print_exc()
      if DEV_MODE:
        print(f"🔧 MODO DESARROLLO - Código disponible en consola:")
        print(f"   📝 {plain_text}")

  # Ejecutar envío en un hilo separado para no bloquear la petición HTTP
  thread = threading.Thread(target=_send_sync, daemon=True)
  thread.start()
  print(f"🔧 Correo encolado para envío a {to_email}")
  return True


def enviarCorreo(correo, codigoVerificacion):
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
    return _send_email(correo, subject, plain, html)


def enviarCorreoCambio(correo):
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
    _send_email(correo, subject, plain, html)


def enviarCorreoVerificacion(correo, codigoVerificacion):
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
    _send_email(correo, subject, plain, html)


def enviarCorreoReserva(correo, mensaje):
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
    _send_email(correo, subject, plain, html)


def enviarCorreoCancelacion(correo, nombre, mensaje_extra, es_cliente=True):
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
    _send_email(correo, subject, plain, html)