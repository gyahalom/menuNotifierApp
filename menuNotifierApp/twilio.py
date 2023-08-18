from http_logging.handler import AsyncHttpHandler
from http_logging.transport import AsyncHttpTransport
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
  From,
	Mail,
  HtmlContent,
	ReplyTo,
	Subject,
	To,
)
from twilio.rest import Client
from typing import Optional, List

APP_NAME = 'Menu Notifier'
ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
SERVICE_ID = os.getenv('TWILIO_SERVICE_ID')
VERIFY_SID = os.getenv('TWILIO_VERIFY_SID')		
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
SENDGRID_FROM_EMAIL = os.getenv('SENDGRID_FROM_EMAIL')
SENDGRID_TO_EMAIL = os.getenv('SENDGRID_TO_EMAIL')
client = Client(ACCOUNT_SID, AUTH_TOKEN)

def send_email(subject: str, body: str, reply_to: Optional[tuple[str]]=None) -> None:
	mail = Mail(
		from_email=From(SENDGRID_FROM_EMAIL, APP_NAME),
		to_emails=To(SENDGRID_TO_EMAIL),
		subject=Subject(f'[{APP_NAME}] {subject}'),
		html_content=HtmlContent(body))
	if reply_to is not None:
		mail.reply_to = ReplyTo(*reply_to)
	sg = SendGridAPIClient()
	sg.send(mail)

def send_text(phone: str, body: str) -> None:
	client.messages.create(  
		messaging_service_sid=SERVICE_ID, 
		body=body,      
		to=phone,
	) 

def verify_send(phone: str) -> None:
	client.verify \
				.v2 \
				.services(VERIFY_SID) \
				.verifications \
				.create(to=phone, channel='sms')

def verify_check(phone: str, code: str) -> bool:
	verification_check = client.verify \
															.v2 \
															.services(VERIFY_SID) \
															.verification_checks \
															.create(to=phone, code=code)
	return verification_check.status == 'approved'

# Based on tutorial from 
# https://www.twilio.com/blog/python-error-alerting-twilio-sendgrid
class TwilioHttpTransport(AsyncHttpTransport):
	def __init__(
			self,
			logger_name: str,
			twilio_account_sid: Optional[str] = None,
			twilio_auth_token: Optional[str] = None,
			twilio_sender_number: Optional[str] = None,
			sendgrid_sender_email: Optional[str] = None,
			sendgrid_api_key: Optional[str] = None,
			alert_phone: Optional[str] = None,
			alert_email: Optional[List[str]] = None,
			*args,
			**kwargs,
	) -> None:
		self.logger_name = logger_name
		self.alert_context = f'[{logger_name}] Alert from logger'

		self.twilio_account_sid = twilio_account_sid
		self.twilio_auth_token = twilio_auth_token
		self.twilio_sender_number = twilio_sender_number

		self.sendgrid_sender_email = sendgrid_sender_email
		self.sendgrid_api_key = sendgrid_api_key

		self.alert_phone = alert_phone
		self.alert_email = alert_email
		super().__init__(*args, **kwargs)

	def send(self, events: List[bytes], **kwargs) -> None:
		batches = list(self._HttpTransport__batches(events))

		if self.alert_phone:
			self.send_sms_alert(batches=batches)

		if self.alert_email:
			self.send_email_alert(batches=batches)

	def send_sms_alert(self, batches: List[dict]) -> None:
		twilio_client = Client(
			username=self.twilio_account_sid,
			password=self.twilio_auth_token,
		)

		sms_logs = ', '.join([
			f"{log['level']['name']}: {log['message']}"
			for batch in batches
			for log in batch
		])

		twilio_client.messages.create(
			body=f'[{self.alert_context}] {sms_logs}',
			from_=self.twilio_sender_number,
			to=self.alert_phone,
		)

	def send_email_alert(self, batches: List[dict]) -> None:
		msg = '<hr>'.join([
			self.build_log_html(log)
			for batch in batches
			for log in batch
		])

		send_email(subject=self.alert_context, body=msg)
		message = Mail(
			from_email=self.sendgrid_sender_email,
			to_emails=self.alert_email,
			subject=self.alert_context,
			html_content=msg,
		)

		sg = SendGridAPIClient(self.sendgrid_api_key)
		sg.send(message)

	def build_log_html(self, log):
		return '<br>'.join([
			f'<b>{key}:</b> {val}'
			for key, val in log.items()
		])
	
transport_class = TwilioHttpTransport(
	logger_name=APP_NAME,
	sendgrid_api_key=SENDGRID_API_KEY,
	sendgrid_sender_email=SENDGRID_FROM_EMAIL,
	alert_email=SENDGRID_TO_EMAIL,
)

twilio_handler = AsyncHttpHandler(transport_class=transport_class)