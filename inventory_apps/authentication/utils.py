import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class Util:
    @staticmethod
    def send_email(data):
        try:
            url = "https://api.resend.com/emails"

            resend_api_key = getattr(settings, "RESEND_API_KEY", None)
            resend_from_email = getattr(settings, "RESEND_FROM_EMAIL", None)

            if not resend_api_key:
                logger.error("RESEND_API_KEY is missing in settings.py")
                return False

            if not resend_from_email:
                logger.error("RESEND_FROM_EMAIL is missing in settings.py")
                return False

            headers = {
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "from": resend_from_email,
                "to": [data["to_email"]],
                "subject": data["email_subject"],
                "html": data["email_body"],
            }

            response = requests.post(url, json=payload, headers=headers, timeout=15)

            if response.status_code in [200, 201, 202]:
                logger.info(f"Email sent successfully to {data['to_email']}")
                return True

            logger.error(
                f"Failed to send email. Status: {response.status_code}, Response: {response.text}"
            )
            return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Resend request error: {str(e)}")
            return False

        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return False