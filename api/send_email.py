import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import time

def send_verification_email(to_email: str, code: str):
    from_email = os.environ.get("EMAIL_SERVER_USER")
    password = os.environ.get("EMAIL_SERVER_PASS")
    smtp_server = os.environ.get("EMAIL_SERVER_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SERVER_PORT", 587))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Welcomepage Verification Code"
    msg["From"] = "noreply@welcomepage.app"
    msg["To"] = to_email
    # Cache-bust the logo so Yahoo's image proxy doesn't serve an old version
    logo_base = (os.environ.get("WEBAPP_URL") or "https://welcomepage.app")
    cache_buster = str(int(time.time()))
    logo_src = f"{logo_base}/welcomepage-logo.png?v={cache_buster}"

    # Plaintext fallback for clients that don't render HTML or when Yahoo/Gmail choose text part
    text_part = f"""
Your Welcomepage Verification Code

Code: {code}

Enter this code in the app to continue signing in.
If you didn't request this, you can safely ignore this email.
"""

    # Bulletproof, table-based HTML that renders consistently across Yahoo/Gmail/Outlook
    # Use px units, explicit widths, and align=center instead of margin auto.
    html = f"""
<!DOCTYPE html>
<html>
  <head>
    <meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>Welcomepage Verification</title>
  </head>
  <body style=\"margin:0; padding:0; background-color:#f6f7f9;\">
    <!-- Preheader (hidden) -->
    <div style=\"display:none; font-size:1px; color:#f6f7f9; line-height:1px; max-height:0; max-width:0; opacity:0; overflow:hidden;\">Your verification code is {code}.</div>

    <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" width=\"100%\" style=\"background-color:#f6f7f9;\">
      <tr>
        <td align=\"center\" style=\"padding:24px 12px;\">
          <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" width=\"480\" style=\"width:480px; max-width:480px; background-color:#ffffff; border:1px solid #eeeeee; border-radius:16px;\">
            <tr>
              <td align=\"center\" style=\"background-color:#d6edfc; padding:20px 16px; border-top-left-radius:16px; border-top-right-radius:16px;\">
                <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" width=\"300\" style=\"width:300px; max-width:300px;\">
                  <tr>
                    <td align=\"center\" width=\"300\" style=\"width:300px;\">
                      <img src=\"{logo_src}\" alt=\"Welcomepage\" width=\"300\" height=\"90\" style=\"display:block; border:0; outline:none; text-decoration:none; width:300px !important; max-width:300px !important; height:auto;\" />
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align=\"center\" style=\"padding:32px 24px 8px 24px; font-family:Arial, sans-serif;\">
                <div style=\"font-size:20px; color:#111827; font-weight:700;\">Your Verification Code</div>
              </td>
            </tr>
            <tr>
              <td align=\"center\" style=\"padding:8px 24px 16px 24px;\">
                <div style=\"font-family:Arial, sans-serif; font-size:40px; letter-spacing:8px; color:#3c82f6; font-weight:700;\">{code}</div>
              </td>
            </tr>
            <tr>
              <td align=\"center\" style=\"padding:0 24px 24px 24px;\">
                <div style=\"font-family:Arial, sans-serif; font-size:16px; color:#374151;\">Enter this code in the app to continue signing in.</div>
              </td>
            </tr>
            <tr>
              <td align=\"center\" style=\"padding:0 24px 32px 24px;\">
                <div style=\"font-family:Arial, sans-serif; font-size:14px; color:#6b7280;\">If you didn't request this, you can safely ignore this email.</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
  </html>
    """

    # Attach text first, then HTML (some clients pick the first alternative)
    msg.attach(MIMEText(text_part, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(from_email, password)
        server.sendmail(from_email, to_email, msg.as_string())

