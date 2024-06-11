from datetime import datetime, timedelta
import os
import requests
from typing import Iterable, Optional
from .db import get_db
from .twilio import send_text

MENU_ID = {
	'BREAKFAST': {
		'id': '6136d437534a13f81e174a81',
		'long': False,
	},
	'LUNCH': {
		'id': '55a02d4deabc88225e8b473f',
		'long': True,
	},
}
SCHOOL = 'McAuliffe'
MENU_ID_URL = 'https://www.schoolnutritionandfitness.com/webmenus2/api/menutypeController.php/show'
MENU_ITEM_URL = 'https://api.isitesoftware.com/graphql'
base = os.path.dirname(os.path.realpath(__file__))

def suffix(d: int) -> str:
	return 'th' if 11 <= d <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')

def custom_strftime(format: str, t: datetime) -> str:
	return t.strftime(format).replace('{S}', str(t.day) + suffix(t.day))

def greet(hour: Optional[int]=None) -> str:
	hour = datetime.now().hour if hour is None else hour
	if 6 <= hour < 12:
		greet = 'Morning'
	elif 12 <= hour < 17:
		greet = 'Afternoon'
	elif 17 <= hour < 20:
		greet = 'Evening'
	else:
		greet = 'Night'

	return f'Good {greet}'

def get_menu_id(meal_id: str, 
								month: Optional[int]=None, 
								year: Optional[int]=None) -> str:
	today = datetime.today()
	month = month or today.month
	year = year or today.year
	payload = {'_id': meal_id}
	r = requests.get(MENU_ID_URL, params=payload)
	r.raise_for_status()
	menus = r.json()
	if (menus is None) or ('menus' not in menus):
		raise ValueError('No menu data retrieved')
	menu_id = next((x['id'] for x in menus['menus'] if x['year'] == year and 
									x['month'] == month-1), None)
	if menu_id is None:
		raise ValueError(f'No menu found for {month}/{year}')		
	
	return menu_id

def get_menu_items(menu_id: str, day: Optional[int]=None) -> Iterable[dict]:
	today = datetime.today()
	day = day or today.day
	query = ('{menu(id:"' + menu_id + '") {id month year items{day product{id ' +
						'name long_description category}}}}')
	payload = {'query': query}
	r = requests.get(MENU_ITEM_URL, params=payload)
	r.raise_for_status()
	items = r.json()
	if (items is None) or ('data' not in items):
		raise ValueError('No menu item data retrieved')
	options = [x['product'] for x in items['data']['menu']['items'] if 
							x['day'] == day and x['product']['category'] != 'Ancillary']
	return options

def get_item_details(item_id: str) -> dict:
	query = '{product(id:"' + item_id + '") {id name image_url1 long_description}}'
	payload = {'query': query}
	r = requests.get(MENU_ITEM_URL, params=payload)
	r.raise_for_status()
	item = r.json()
	if (item is None) or ('data' not in item):
		raise ValueError('No item data retrieved')
	return item['data']['product']

def gen_message(meal: dict, date: Optional[datetime]=None) -> str:	
	msg = []
	date = date or datetime.now()
	menu_id = get_menu_id(meal['id'], month=date.month, year=date.year)
	items = get_menu_items(menu_id, day=date.day)
	for item in items:
		# item_details = get_item_details(item['id'])
		if meal['long']:
			desc = item['long_description'].split('\n')[0] if item['long_description'] else ''
			msg.append(f"{item['name']}: {desc}")
			msg.append('OR')
		else:
			msg.append(f"{item['name']}, ")
	if msg:
		if meal['long']:
			msg.pop()
		else:			
			msg[-1] = msg[-1][:-2]
			if len(msg) > 1:
				msg[-2] = msg[-2][:-2] + ' and '
			msg = [''.join(msg)]
	
	return msg

def send_messages(date: datetime=None, msg=None):
	if msg is None:
		if date is None:
			date = datetime.now() + timedelta(days=1)
		date_str = custom_strftime('%A, %B {S}, %Y', date)
		msg = []

		meals = ['Breakfast', 'Lunch']
		for meal in meals:
			try:			
				meal_msg = gen_message(MENU_ID[meal.upper()], date=date)
			except:
				meal_msg = None
			if meal_msg:
				prefix = f'{meal} option'
				prefix += 's are:' if len(meal_msg) > 1 else ' is:'
				msg.append(prefix)
				msg.extend(meal_msg)
				msg.append('')
		if msg:		
			msg = [f'{SCHOOL} meal options for {date_str}', ''] + msg + ['Have a nice day!']
	elif os.path.isfile(msg):
		with open(msg) as f:
			msg = f.read().splitlines()		
	elif isinstance(msg, str):
		msg = msg.splitlines()

	if msg:		
		db = get_db()
		users = db.execute('SELECT * FROM user').fetchall()
		msg.insert(0, '')
		for person in users:
			msg[0] = f"\n{greet()} {person['username']},"
			send_text(phone=person['phone'], body='\n'.join(msg))
	