import atexit
from dotenv import load_dotenv
from flask import (
  has_request_context, 
  request, 
  Flask, 
  flash, 
  redirect, 
  url_for, 
  render_template,
)
from flask.logging import default_handler
from flask_apscheduler import APScheduler
from flask_apscheduler.utils import CronTrigger
from flask_bootstrap import Bootstrap5
from flask_wtf import FlaskForm
from http_logging.handler import AsyncHttpHandler
import os
import logging
from logging.config import dictConfig
from logging.handlers import TimedRotatingFileHandler
from .menu_notifier import send_messages
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
  From,
	Mail,
  PlainTextContent,
	ReplyTo,
	Subject,
	To,
)
from wtforms.validators import DataRequired
from wtforms.fields import (
  EmailField, 
  StringField, 
  SubmitField, 
  TextAreaField,
)
from .twilio import (
	TwilioHttpTransport,
	SENDGRID_API_KEY,
	SENDGRID_FROM_EMAIL,
	SENDGRID_TO_EMAIL,
)

APP_NAME = 'Menu Notifier'
CRONTAB = os.getenv('MENU_NOTIFIER_CRON', '0 19 * * 0-3,6')

transport_class = TwilioHttpTransport(
	logger_name=APP_NAME,
	sendgrid_api_key=SENDGRID_API_KEY,
	sendgrid_sender_email=SENDGRID_FROM_EMAIL,
	alert_email=SENDGRID_TO_EMAIL,
)

twilio_handler = AsyncHttpHandler(transport_class=transport_class)
twilio_handler.setLevel(logging.ERROR)

dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }},
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    }
})

class RequestFormatter(logging.Formatter):
	def format(self, record):
		if has_request_context():
			record.url = request.url
			record.remote_addr = request.remote_addr
		else:
			record.url = None
			record.remote_addr = None

		return super().format(record)

formatter = RequestFormatter(
    '[%(asctime)s] %(remote_addr)s requested %(url)s\n'
    '%(levelname)s in %(module)s: %(message)s'
)
default_handler.setFormatter(formatter)

load_dotenv()

class ContactForm(FlaskForm):
	name = StringField('Name', render_kw={'placeholder': 'Your name'}, 
											validators=[DataRequired()])
	email = EmailField('Email', render_kw={'placeholder': 'Your email address'}, 
		  								validators=[DataRequired()])
	subject = StringField('Subject', render_kw={'placeholder': 'What''s it about'}, 
												validators=[DataRequired()])
	message = TextAreaField('Message', render_kw={'placeholder': 'Your message'}, 
											validators=[DataRequired()])
	submit = SubmitField('Send')

def create_app(test_config=None):
	# create and configure the app
	app = Flask(__name__, instance_relative_config=True)
	app.config.from_mapping(
		SECRET_KEY='dev',
		DATABASE=os.path.join(app.instance_path, 'menuNotifier.sqlite'),
	)

	if test_config is None:
		# load config from environment variables
		app.config.from_prefixed_env()
	else:
		# load the test config if passed in
		app.config.from_mapping(test_config)

	# ensure the instance folder exists
	if not os.path.isdir(app.instance_path):
		try:
			os.makedirs(app.instance_path)
		except OSError:
			app.logger.exception('Failed to create instance folder')

	# Add email logging handler
	app.logger.addHandler(twilio_handler)
	rot_handler = TimedRotatingFileHandler(
		os.path.join(app.instance_path, 'menuNotifier.log'), 
		when='midnight',
		backupCount=6,
	)
	rot_handler.setLevel(logging.INFO)
	rot_handler.setFormatter(formatter)
	app.logger.addHandler(rot_handler)

	bootstrap = Bootstrap5()
	bootstrap.init_app(app)

	from . import db
	db.init_app(app)

	from . import signup
	app.register_blueprint(signup.bp)

	from . import policies
	app.register_blueprint(policies.bp)

	@app.route('/')
	def home():
		return redirect(url_for('signup.signup'))
	
	@app.route('/contact', methods=('GET', 'POST'))
	def contact():
		form = ContactForm()
		error = None
		if form.validate_on_submit():
			app.logger.info('Sending contact email')			
			mail = Mail(
				from_email=From(SENDGRID_FROM_EMAIL, APP_NAME),
				to_emails=To(SENDGRID_TO_EMAIL),
				subject=Subject(f'[{APP_NAME}][User Contact] {form.subject.data}'),
				plain_text_content=PlainTextContent(form.message.data))
			mail.reply_to = ReplyTo(form.email.data, form.name.data)
			try:
				sg = SendGridAPIClient()
				sg.send(mail)
				form = ContactForm(formdata=None)
				flash('Message sent!', 'success')
			except:
				app.logger.exception('Failed to send user contact message')
				error = 'Failed to send message, please try again later'

		if error is not None:
			flash(error, 'error')
		
		return render_template('contact.html', form=form)

	scheduler = APScheduler()
	scheduler.init_app(app)	
	@scheduler.task(
		CronTrigger.from_crontab(CRONTAB),
		id='send_sms',		
	)
	def sens_sms():
		"""
		Send notifications Weekdays at 7pm
		"""
		try:
			with app.app_context():
				app.logger.info('Sending messages')
				send_messages()
		except:
			app.logger.exception('Failed to send messages')

	scheduler.start()
	@atexit.register
	def close_scheduler():
		if scheduler.running:
			app.logger.info('Shutting down the scheduler')
			scheduler.shutdown()

	@app.errorhandler(404)
	def page_not_found(e):
		return render_template('error/404.html'), 404

	@app.errorhandler(500)
	def internal_server_error(e):
		return render_template('error/500.html'), 500

	return app