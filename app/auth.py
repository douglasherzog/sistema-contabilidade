from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from .extensions import db
from .models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.get("/login")
def login():
    return render_template("auth/login.html")


@auth_bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not email or not password:
        flash("Informe e-mail e senha.", "warning")
        return redirect(url_for("auth.login"))

    u = User.query.filter_by(email=email).first()
    if not u or not u.check_password(password):
        flash("Credenciais inválidas.", "danger")
        return redirect(url_for("auth.login"))

    login_user(u)
    return redirect(url_for("main.index"))


@auth_bp.get("/register")
def register():
    return render_template("auth/register.html")


@auth_bp.post("/register")
def register_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not email or not password:
        flash("Informe e-mail e senha.", "warning")
        return redirect(url_for("auth.register"))

    if User.query.filter_by(email=email).first():
        flash("E-mail já cadastrado.", "warning")
        return redirect(url_for("auth.register"))

    u = User(email=email, is_admin=False)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()

    flash("Conta criada. Faça login.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
