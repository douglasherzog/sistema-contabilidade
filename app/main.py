from flask import Blueprint, render_template
from flask_login import login_required, current_user


main_bp = Blueprint("main", __name__)


@main_bp.get("/")
@login_required
def index():
    return render_template("index.html", user=current_user)
