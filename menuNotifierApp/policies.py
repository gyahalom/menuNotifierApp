from flask import (
  Blueprint, 
  render_template, 
)

bp = Blueprint('policies', __name__, url_prefix='/policies')

@bp.route('/privacy')
def privacy():
	return render_template('policies/privacy.html')

@bp.route('/terms')
def terms():
	return render_template('policies/terms.html')