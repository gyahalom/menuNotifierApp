from flask import (
  Blueprint, 
  flash, 
  Markup,
  redirect, 
  render_template, 
  request, 
  session, 
  url_for,
)
from flask import current_app as app
from flask_wtf import FlaskForm
import re
from wtforms.validators import (
  DataRequired, 
  Regexp, 
  AnyOf
)
from wtforms.fields import (
  BooleanField, 
  StringField, 
	SubmitField, 
  TelField, 
  Label
)
from .db import get_db
from .twilio import (
  send_email, 
  verify_send, 
  verify_check,
)

bp = Blueprint('signup', __name__, url_prefix='/signup')
PHONE_PAT = '^\s*(?:\+1)?\s*\(?(\d{3})\)?\s*(\d{3})\s*-?\s*(\d{4})\s*$'

class PhoneForm(FlaskForm):
	name = StringField('Name', render_kw={'autocomplete': 'given-name',
											'placeholder': 'Name used in messages'}, 
											validators=[DataRequired()])
	phone = TelField('Phone', render_kw={'autocomplete': 'tel-national', 
				      			'placeholder': 'Your phone number'}, 
		  							validators=[DataRequired(), Regexp(PHONE_PAT, 
										message='Incorrect phone format, should be (xxx) yyy-zzzz')])
	terms = BooleanField(default=False, validators=[AnyOf([True], 
												message='You must agree to the terms to sign up')])
	submit = SubmitField()

class VerifyForm(FlaskForm):
	code = StringField('Code', render_kw={'autocomplete': 'one-time-code'}, 
		    							validators=[DataRequired(), Regexp('^\d{6}$', 
							       	message="Code should be 6 digits")])
	submit = SubmitField('Verify')

def phone_exists(phone):
	db = get_db()
	user = db.execute(
		'SELECT * FROM user WHERE phone = ?', 
		(phone,)
	).fetchone()
	return user is not None

def get_retries(phone):
	db = get_db()
	retries = db.execute(
		'SELECT * FROM retries WHERE phone = ?', 
		(phone,)
	).fetchone()
	return retries['retry'] if retries else 0

@bp.route('/', methods=('GET', 'POST'))
def signup():
	form = PhoneForm()
	form.terms.label = Label(form.terms.id, Markup(
		'By signing up you agree to the '
		f'<a href="{ url_for("policies.terms") }">Terms and Conditions</a> and '
		f'<a href="{ url_for("policies.privacy") }"> Privacy policy</a>'
	))
	if form.validate_on_submit():
		name = form.name.data
		phone = form.phone.data
		app.logger.info(f'User {name} trying to sign up with phone {phone}')
		error = None

		if not form.terms.data:
			error = 'Must agree to terms'
		elif not name:
			error = 'Name is required'
		elif not phone:
			error = 'Phone is required'
		# Sanitize and normalize phone number
		phone = re.match(PHONE_PAT, phone)
		if phone is None:
			error = 'Incorrect phone format, should be (xxx) yyy-zzzz'		
		else:
			phone = '+1' + ''.join(phone.groups())
			if phone_exists(phone):
				return render_template('signup/success.html')

		if error is None:
			session.clear()
			session['name'] = name
			session['phone'] = phone
			return redirect(url_for("signup.verify"))
		else:
			app.logger.info(f'User encountered error: {error}')
			flash(error, 'error')

	return render_template('signup/signup.html', form=form)

@bp.route('/verify', methods=('GET', 'POST'))
def verify():
	if 'phone' not in session or 'name' not in session:
		return redirect(url_for('signup.signup'))
	name = session['name']
	phone = session['phone']
	form = VerifyForm()
	error = None
	if phone_exists(phone):
		return render_template('signup/success.html')
	if (retries := get_retries(phone)) > 5:
		error = 'There was an issue sending code'
	if error is None:		
		if request.method == 'GET':
			try:
				app.logger.info(f'Sending verification code to {phone}')
				verify_send(phone)
			except:
				error = 'Could not send verification code'
				app.logger.exception('Failed to send verification code')
			else:
				db = get_db()
				# Increment retries
				try:
					if retries == 0:
						db.execute(
							'INSERT INTO retries (phone, retry) VALUES (?, 1)',
							(phone,),
						)
					else:
						db.execute(
								'UPDATE retries SET retry = retry + 1 WHERE phone = ?',
								(phone,),
							)
					db.commit()	
					session['retries'] = 0
				except db.IntegrityError:
					app.logger.exception('Failed to update DB')	
		if form.validate_on_submit():
			session['retries'] = session.get('retries', 0) + 1
			if session['retries'] > 5:
				error = 'Too many attempts. Try again later'
			else:
				try:
					check = verify_check(phone, form.code.data)
				except:
					error = 'Could not verify code'
					app.logger.exception('Failed to verify code')
				else:
					if check:
						app.logger.info('User successfully verified, adding to DB')
						try:
							db = get_db()
							db.execute(
									'DELETE FROM retries WHERE phone = ?',
									(phone,),
								)
							db.execute(
								'INSERT INTO user (username, phone) VALUES (?, ?)',
								(name, phone),
							)
							db.commit()		
							send_email(
								subject='New User Signed Up!', 
								body=f'{name} registered with phone {phone}',
							)
						except db.IntegrityError:
							error = 'Something went wrong, please try again'	
							app.logger.exception('Failed to update DB')	
						else:
							return render_template('signup/success.html')
					else:
						error = 'Incorrect code, try again'

	if error is not None:
		app.logger.info(f'User encountered error: {error}')
		flash(error, 'error')

	return render_template('signup/verify.html', form=form, phone=phone[-4:])
	