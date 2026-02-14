from __future__ import annotations

from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id: str):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    legal_name = db.Column(db.String(255), nullable=False, default="")
    trade_name = db.Column(db.String(255), nullable=False, default="")
    cnpj = db.Column(db.String(30), nullable=False, default="")
    cnae = db.Column(db.String(20), nullable=False, default="")
    city = db.Column(db.String(120), nullable=False, default="")
    state = db.Column(db.String(2), nullable=False, default="RS")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    cpf = db.Column(db.String(20), nullable=True)
    hired_at = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    salaries = db.relationship(
        "EmployeeSalary",
        backref="employee",
        cascade="all, delete-orphan",
        order_by="EmployeeSalary.effective_from.desc()",
        lazy=True,
    )


class EmployeeDependent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    full_name = db.Column(db.String(255), nullable=False)
    cpf = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class EmployeeSalary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    effective_from = db.Column(db.Date, nullable=False, index=True)
    base_salary = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PayrollRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    overtime_hour_rate = db.Column(db.Numeric(12, 2), nullable=False, default=12.45)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    lines = db.relationship(
        "PayrollLine",
        backref="payroll_run",
        cascade="all, delete-orphan",
        lazy=True,
    )

    __table_args__ = (db.UniqueConstraint("year", "month", name="uq_payroll_run_year_month"),)

    def competence_start(self) -> date:
        return date(int(self.year), int(self.month), 1)


class PayrollLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey("payroll_run.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    base_salary = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    overtime_hours = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    overtime_hour_rate = db.Column(db.Numeric(12, 2), nullable=False, default=12.45)
    overtime_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    gross_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    employee = db.relationship("Employee")

    __table_args__ = (db.UniqueConstraint("payroll_run_id", "employee_id", name="uq_payroll_line_run_employee"),)


class GuideDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    doc_type = db.Column(db.String(20), nullable=False, index=True)  # darf | das | fgts
    filename = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    paid_at = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("year", "month", "doc_type", name="uq_guide_doc_year_month_type"),)


class TaxInssBracket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    effective_from = db.Column(db.Date, nullable=False, index=True)
    up_to = db.Column(db.Numeric(12, 2), nullable=True)  # None = sem teto (última faixa)
    rate = db.Column(db.Numeric(8, 6), nullable=False)  # ex.: 0.075
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TaxIrrfConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    effective_from = db.Column(db.Date, nullable=False, index=True)
    dependent_deduction = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TaxIrrfBracket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    effective_from = db.Column(db.Date, nullable=False, index=True)
    up_to = db.Column(db.Numeric(12, 2), nullable=True)  # None = sem teto (última faixa)
    rate = db.Column(db.Numeric(8, 6), nullable=False)  # ex.: 0.075
    deduction = db.Column(db.Numeric(12, 2), nullable=False, default=0)  # parcela a deduzir
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
