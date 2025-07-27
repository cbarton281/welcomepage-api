import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

def send_verification_email(to_email: str, code: str):
    from_email = os.environ.get("EMAIL_SERVER_USER")
    password = os.environ.get("EMAIL_SERVER_PASS")
    smtp_server = os.environ.get("EMAIL_SERVER_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SERVER_PORT", 587))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Welcomepage Verification Code"
    msg["From"] = "noreply@welcomepage.app"
    msg["To"] = to_email
    logo_url = os.environ.get("PUBLIC_ASSETS_URL") + "/welcomepage-logo.png"

    html = f'''
      <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; border: 1px solid #eee; border-radius: 16px; overflow: hidden; background-color: #fff; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);">
        <div style="background-color: #d6edfc; padding: 24px 0; text-align: center; border-top-left-radius: 16px; border-top-right-radius: 16px;">
          <img src="{logo_url}" alt="Welcomepage Logo" style="height: 48px;" />
        </div>
        <div style="padding: 32px 24px; text-align: center;">
          <h2 style="font-size: 1.25rem; color: #111827; margin-bottom: 16px;">Your Verification Code</h2>
          <div style="font-size: 2.5rem; letter-spacing: 0.5rem; color: #3c82f6; font-weight: bold; margin-bottom: 24px;">{code}</div>
          <p style="font-size: 1rem; color: #374151;">Enter this code in the app to continue signing in.</p>
          <p style="font-size: 0.9rem; color: #6b7280; margin-top: 32px;">If you didn't request this, you can safely ignore this email.</p>
        </div>
      </div>
      '''

    part = MIMEText(html, "html")
    msg.attach(part)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(from_email, password)
        server.sendmail(from_email, to_email, msg.as_string())

