from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required
from werkzeug.utils import secure_filename

from .extensions import db
from .models import (
    CompetenceClose,
    Employee,
    EmployeeDependent,
    EmployeeVacation,
    EmployeeSalary,
    GuideDocument,
    RevenueNote,
    PayrollLine,
    PayrollRun,
    TaxInssBracket,
    TaxIrrfBracket,
    TaxIrrfConfig,
)


payroll_bp = Blueprint("payroll", __name__, url_prefix="/payroll")


def _to_decimal(v: str | None, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if v is None:
            return default
        s = str(v).strip()
        if not s:
            return default
        s = s.replace(".", "").replace(",", ".") if "," in s else s
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return default


def _parse_date(v: str | None) -> date | None:
    s = (v or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        pass
    try:
        parts = s.split("/")
        if len(parts) != 3:
            return None
        dd, mm, yyyy = (p.strip() for p in parts)
        if len(yyyy) == 2:
            yyyy = "20" + yyyy
        return date(int(yyyy), int(mm), int(dd))
    except Exception:
        return None


def _media_guides_dir() -> str:
    p = os.path.join(current_app.instance_path, "media", "guides")
    os.makedirs(p, exist_ok=True)
    return p


def _competence_start(year: int, month: int) -> date:
    return date(int(year), int(month), 1)


def _competence_is_closed(year: int, month: int) -> bool:
    return CompetenceClose.query.filter_by(year=int(year), month=int(month)).first() is not None


def _calc_revenue_month_summary(year: int, month: int) -> dict:
    notes = RevenueNote.query.filter_by(year=int(year), month=int(month)).all()
    total = Decimal("0")
    for n in notes:
        try:
            total += Decimal(str(n.amount or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))
    return {
        "count": len(notes),
        "total": total,
    }


def _calc_vacation_amounts(base_salary: Decimal, days: int, sell_days: int) -> dict:
    # Fixed-salary version (no averages). Uses 30-day base.
    d = max(0, int(days or 0))
    s = max(0, int(sell_days or 0))
    daily = (base_salary / Decimal("30")) if base_salary > 0 else Decimal("0")
    vacation_pay = (daily * Decimal(str(d))).quantize(Decimal("0.01"))
    vacation_one_third = (vacation_pay / Decimal("3")).quantize(Decimal("0.01"))
    abono_pay = (daily * Decimal(str(s))).quantize(Decimal("0.01"))
    abono_one_third = (abono_pay / Decimal("3")).quantize(Decimal("0.01"))
    gross_total = (vacation_pay + vacation_one_third + abono_pay + abono_one_third).quantize(Decimal("0.01"))
    return {
        "daily": daily.quantize(Decimal("0.0001")) if daily else Decimal("0"),
        "vacation_pay": vacation_pay,
        "vacation_one_third": vacation_one_third,
        "abono_pay": abono_pay,
        "abono_one_third": abono_one_third,
        "gross_total": gross_total,
    }


def _calc_vacations_month_summary(year: int, month: int) -> dict:
    rows = EmployeeVacation.query.filter_by(year=int(year), month=int(month)).all()
    total = Decimal("0")
    for r in rows:
        try:
            total += Decimal(str(r.gross_total or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))
    return {
        "count": len(rows),
        "total_gross": total,
    }


def _salary_for_employee(employee: Employee, year: int, month: int) -> Decimal:
    comp = _competence_start(year, month)
    s = (
        EmployeeSalary.query.filter(EmployeeSalary.employee_id == employee.id)
        .filter(EmployeeSalary.effective_from <= comp)
        .order_by(EmployeeSalary.effective_from.desc())
        .first()
    )
    if not s:
        return Decimal("0")
    try:
        return Decimal(str(s.base_salary))
    except Exception:
        return Decimal("0")


def _latest_inss_brackets(effective_date: date):
    eff = (
        db.session.query(TaxInssBracket.effective_from)
        .filter(TaxInssBracket.effective_from <= effective_date)
        .order_by(TaxInssBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )
    if not eff:
        return None, []
    rows = TaxInssBracket.query.filter_by(effective_from=eff).order_by(TaxInssBracket.up_to.asc().nullslast()).all()
    return eff, rows


def _latest_irrf_config(effective_date: date):
    return (
        TaxIrrfConfig.query.filter(TaxIrrfConfig.effective_from <= effective_date)
        .order_by(TaxIrrfConfig.effective_from.desc())
        .first()
    )


def _latest_irrf_brackets(effective_date: date):
    eff = (
        db.session.query(TaxIrrfBracket.effective_from)
        .filter(TaxIrrfBracket.effective_from <= effective_date)
        .order_by(TaxIrrfBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )
    if not eff:
        return None, []
    rows = TaxIrrfBracket.query.filter_by(effective_from=eff).order_by(TaxIrrfBracket.up_to.asc().nullslast()).all()
    return eff, rows


def _calc_inss_progressive(base: Decimal, brackets: list[TaxInssBracket]) -> Decimal:
    if base <= 0:
        return Decimal("0")
    remaining = base
    prev = Decimal("0")
    total = Decimal("0")
    for b in brackets:
        up_to = Decimal(str(b.up_to)) if b.up_to is not None else None
        rate = Decimal(str(b.rate or 0))
        if rate <= 0:
            continue
        if up_to is None:
            taxable = max(Decimal("0"), remaining)
        else:
            taxable = max(Decimal("0"), min(base, up_to) - prev)
        if taxable > 0:
            total += (taxable * rate)
        if up_to is not None:
            prev = up_to
        if base <= prev:
            break
    return total.quantize(Decimal("0.01"))


def _calc_irrf(base: Decimal, cfg: TaxIrrfConfig | None, brackets: list[TaxIrrfBracket], dependents_count: int) -> Decimal:
    if base <= 0:
        return Decimal("0")
    dep_ded = Decimal(str(getattr(cfg, "dependent_deduction", 0) or 0)) if cfg else Decimal("0")
    calc_base = base - (dep_ded * Decimal(str(dependents_count or 0)))
    if calc_base <= 0:
        return Decimal("0")

    # IRRF (mensal) tipicamente é por faixa com "parcela a deduzir" (não progressivo no cálculo final).
    chosen = None
    for b in brackets:
        up_to = Decimal(str(b.up_to)) if b.up_to is not None else None
        if up_to is None or calc_base <= up_to:
            chosen = b
            break
    if not chosen:
        return Decimal("0")
    rate = Decimal(str(chosen.rate or 0))
    ded = Decimal(str(chosen.deduction or 0))
    val = (calc_base * rate) - ded
    if val < 0:
        val = Decimal("0")
    return val.quantize(Decimal("0.01"))


def _calc_month_summary(run: PayrollRun | None) -> dict | None:
    if not run:
        return None

    comp = date(int(run.year), int(run.month), 1)
    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()

    total_gross = Decimal("0")
    total_inss = Decimal("0")
    total_irrf = Decimal("0")

    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    for ln in lines:
        gross = (Decimal(str(ln.gross_total or 0)) if ln.gross_total is not None else Decimal("0"))
        total_gross += gross

        deps_count = EmployeeDependent.query.filter_by(employee_id=ln.employee_id).count()
        inss_est = Decimal("0")
        if inss_rows:
            inss_est = _calc_inss_progressive(gross, inss_rows)
        total_inss += inss_est

        irrf_est = Decimal("0")
        if irrf_rows and irrf_cfg:
            irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)
        total_irrf += irrf_est

    total_gross = total_gross.quantize(Decimal("0.01"))
    total_inss = total_inss.quantize(Decimal("0.01"))
    total_irrf = total_irrf.quantize(Decimal("0.01"))
    total_net = (total_gross - total_inss - total_irrf).quantize(Decimal("0.01"))

    return {
        "year": int(run.year),
        "month": int(run.month),
        "employees_count": len(lines),
        "total_gross": total_gross,
        "total_inss_est": (total_inss if inss_rows else None),
        "total_irrf_est": (total_irrf if (irrf_rows and irrf_cfg) else None),
        "total_net_est": (total_net if (inss_rows and irrf_rows and irrf_cfg) else None),
        "inss_eff": inss_eff,
        "irrf_eff": irrf_eff,
        "has_tables": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
    }


@payroll_bp.get("/employees")
@login_required
def employees():
    items = Employee.query.order_by(Employee.active.desc(), Employee.full_name.asc()).all()
    return render_template("payroll/employees.html", items=items)


@payroll_bp.post("/employees")
@login_required
def employees_create():
    full_name = (request.form.get("full_name") or "").strip()
    cpf = (request.form.get("cpf") or "").strip() or None
    hired_at_raw = (request.form.get("hired_at") or "").strip()
    hired_at = _parse_date(hired_at_raw)

    if not full_name:
        flash("Informe o nome do funcionário.", "warning")
        return redirect(url_for("payroll.employees"))

    e = Employee(full_name=full_name, cpf=cpf, hired_at=hired_at)
    db.session.add(e)
    db.session.commit()
    flash("Funcionário cadastrado.", "success")
    return redirect(url_for("payroll.employee_detail", employee_id=e.id))


@payroll_bp.get("/employees/<int:employee_id>")
@login_required
def employee_detail(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    deps = EmployeeDependent.query.filter_by(employee_id=e.id).order_by(EmployeeDependent.id.desc()).all()
    salaries = EmployeeSalary.query.filter_by(employee_id=e.id).order_by(EmployeeSalary.effective_from.desc()).all()
    return render_template("payroll/employee_detail.html", e=e, deps=deps, salaries=salaries)


@payroll_bp.get("/employees/<int:employee_id>/vacations")
@login_required
def employee_vacations(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = EmployeeVacation.query.filter_by(employee_id=e.id).order_by(EmployeeVacation.year.desc(), EmployeeVacation.month.desc(), EmployeeVacation.start_date.desc()).all()
    return render_template(
        "payroll/employee_vacations.html",
        e=e,
        year=year,
        month=month,
        rows=rows,
    )


@payroll_bp.post("/employees/<int:employee_id>/vacations")
@login_required
def employee_vacations_add(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    start_date = _parse_date(request.form.get("start_date"))
    pay_date = _parse_date(request.form.get("pay_date"))
    days = int(request.form.get("days") or 0)
    sell_days = int(request.form.get("sell_days") or 0)

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id))
    if not start_date:
        flash("Informe a data de início das férias.", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))

    if days <= 0 or days > 30:
        flash("Dias de gozo inválidos (1 a 30).", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))
    if sell_days < 0 or sell_days > 10:
        flash("Dias vendidos inválidos (0 a 10).", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))
    if days + sell_days > 30:
        flash("Gozo + venda não pode ultrapassar 30 dias.", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))

    base_salary = _salary_for_employee(e, year, month)
    amounts = _calc_vacation_amounts(base_salary, days, sell_days)

    # Estimate discounts using the same tax tables (didactic, not official).
    comp = _competence_start(year, month)
    deps_count = EmployeeDependent.query.filter_by(employee_id=e.id).count()
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    inss_est = None
    irrf_est = None
    net_est = None
    gross = amounts["gross_total"]
    if inss_rows:
        inss_est = _calc_inss_progressive(gross, inss_rows)
    if irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)
    if inss_est is not None and irrf_est is not None:
        net_est = (gross - inss_est - irrf_est).quantize(Decimal("0.01"))

    row = EmployeeVacation(
        employee_id=e.id,
        year=year,
        month=month,
        start_date=start_date,
        days=days,
        sell_days=sell_days,
        pay_date=pay_date,
        base_salary_at_calc=base_salary,
        vacation_pay=amounts["vacation_pay"],
        vacation_one_third=amounts["vacation_one_third"],
        abono_pay=amounts["abono_pay"],
        abono_one_third=amounts["abono_one_third"],
        gross_total=amounts["gross_total"],
        inss_est=(inss_est if inss_est is not None else None),
        irrf_est=(irrf_est if irrf_est is not None else None),
        net_est=(net_est if net_est is not None else None),
    )
    db.session.add(row)
    db.session.commit()
    flash("Férias registradas.", "success")
    return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))


@payroll_bp.get("/vacations/<int:vac_id>/receipt")
@login_required
def vacation_receipt(vac_id: int):
    v = EmployeeVacation.query.get_or_404(vac_id)

    comp = _competence_start(int(v.year), int(v.month))
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    return render_template(
        "payroll/vacation_receipt.html",
        v=v,
        employee=v.employee,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
        has_tables=bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
    )


@payroll_bp.post("/employees/<int:employee_id>/salary")
@login_required
def employee_add_salary(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    eff_raw = (request.form.get("effective_from") or "").strip()
    base_raw = (request.form.get("base_salary") or "").strip()

    eff = _parse_date(eff_raw)
    if not eff:
        flash("Data de vigência inválida.", "warning")
        return redirect(url_for("payroll.employee_detail", employee_id=e.id))

    base = _to_decimal(base_raw)
    if base <= 0:
        flash("Informe um salário base válido.", "warning")
        return redirect(url_for("payroll.employee_detail", employee_id=e.id))

    s = EmployeeSalary(employee_id=e.id, effective_from=eff, base_salary=base)
    db.session.add(s)
    db.session.commit()
    flash("Salário registrado.", "success")
    return redirect(url_for("payroll.employee_detail", employee_id=e.id))


@payroll_bp.post("/employees/<int:employee_id>/dependent")
@login_required
def employee_add_dependent(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    full_name = (request.form.get("dep_full_name") or "").strip()
    cpf = (request.form.get("dep_cpf") or "").strip() or None
    if not full_name:
        flash("Informe o nome do dependente.", "warning")
        return redirect(url_for("payroll.employee_detail", employee_id=e.id))
    d = EmployeeDependent(employee_id=e.id, full_name=full_name, cpf=cpf)
    db.session.add(d)
    db.session.commit()
    flash("Dependente registrado.", "success")
    return redirect(url_for("payroll.employee_detail", employee_id=e.id))


@payroll_bp.get("/")
@login_required
def payroll_home():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    return render_template("payroll/payroll_home.html", year=year, month=month, run=run)


@payroll_bp.post("/")
@login_required
def payroll_create_or_open():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.payroll_home"))

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    if not run:
        run = PayrollRun(year=year, month=month, overtime_hour_rate=Decimal("12.45"))
        db.session.add(run)
        db.session.flush()

        employees = Employee.query.filter_by(active=True).order_by(Employee.full_name.asc()).all()
        for e in employees:
            base = _salary_for_employee(e, year, month)
            line = PayrollLine(
                payroll_run_id=run.id,
                employee_id=e.id,
                base_salary=base,
                overtime_hours=Decimal("0"),
                overtime_hour_rate=run.overtime_hour_rate,
                overtime_amount=Decimal("0"),
                gross_total=base,
            )
            db.session.add(line)

        db.session.commit()

    return redirect(url_for("payroll.payroll_edit", run_id=run.id))


@payroll_bp.get("/<int:run_id>")
@login_required
def payroll_edit(run_id: int):
    run = PayrollRun.query.get_or_404(run_id)
    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).order_by(PayrollLine.id.asc()).all()
    return render_template("payroll/payroll_edit.html", run=run, lines=lines)


@payroll_bp.post("/<int:run_id>")
@login_required
def payroll_save(run_id: int):
    run = PayrollRun.query.get_or_404(run_id)

    if _competence_is_closed(run.year, run.month):
        flash(
            "Atenção: esta competência está marcada como FECHADA. Você ainda pode alterar, mas revise os relatórios/guias para manter tudo consistente.",
            "warning",
        )

    rate = _to_decimal(request.form.get("overtime_hour_rate"), default=Decimal("12.45"))
    if rate <= 0:
        rate = Decimal("12.45")
    run.overtime_hour_rate = rate

    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
    for ln in lines:
        key = f"overtime_hours_{ln.employee_id}"
        hours = _to_decimal(request.form.get(key), default=Decimal("0"))
        if hours < 0:
            hours = Decimal("0")
        ln.overtime_hours = hours
        ln.overtime_hour_rate = rate
        ln.overtime_amount = (hours * rate).quantize(Decimal("0.01"))
        ln.gross_total = (Decimal(str(ln.base_salary)) + ln.overtime_amount).quantize(Decimal("0.01"))
        db.session.add(ln)

    db.session.add(run)
    db.session.commit()
    flash("Folha salva.", "success")
    return redirect(url_for("payroll.payroll_edit", run_id=run.id))


@payroll_bp.get("/<int:run_id>/holerite/<int:employee_id>")
@login_required
def payroll_holerite(run_id: int, employee_id: int):
    run = PayrollRun.query.get_or_404(run_id)
    ln = PayrollLine.query.filter_by(payroll_run_id=run.id, employee_id=employee_id).first()
    if not ln:
        flash("Funcionário não encontrado nesta folha.", "warning")
        return redirect(url_for("payroll.payroll_edit", run_id=run.id))

    comp = date(int(run.year), int(run.month), 1)
    deps_count = EmployeeDependent.query.filter_by(employee_id=employee_id).count()
    gross = (Decimal(str(ln.gross_total or 0)) if ln.gross_total is not None else Decimal("0"))

    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    inss_est = None
    irrf_est = None
    if inss_rows:
        inss_est = _calc_inss_progressive(gross, inss_rows)
    if irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)

    return render_template(
        "payroll/holerite.html",
        run=run,
        ln=ln,
        deps_count=deps_count,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
        inss_est=inss_est,
        irrf_est=irrf_est,
        irrf_dep_ded=(getattr(irrf_cfg, "dependent_deduction", None) if irrf_cfg else None),
    )


@payroll_bp.get("/config/taxes")
@login_required
def tax_config():
    inss_rows = TaxInssBracket.query.order_by(TaxInssBracket.effective_from.desc(), TaxInssBracket.up_to.asc().nullslast()).all()
    irrf_rows = TaxIrrfBracket.query.order_by(TaxIrrfBracket.effective_from.desc(), TaxIrrfBracket.up_to.asc().nullslast()).all()
    irrf_configs = TaxIrrfConfig.query.order_by(TaxIrrfConfig.effective_from.desc()).all()
    return render_template("payroll/tax_config.html", inss_rows=inss_rows, irrf_rows=irrf_rows, irrf_configs=irrf_configs)


@payroll_bp.post("/config/taxes/inss")
@login_required
def tax_inss_add():
    eff_raw = (request.form.get("effective_from") or "").strip()
    up_to_raw = (request.form.get("up_to") or "").strip()
    rate_raw = (request.form.get("rate") or "").strip()
    eff = _parse_date(eff_raw)
    if not eff:
        flash("Vigência inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    up_to = _to_decimal(up_to_raw) if up_to_raw else None
    rate = _to_decimal(rate_raw)
    if rate <= 0:
        flash("Alíquota inválida. Use formato 0,075 para 7,5%.", "warning")
        return redirect(url_for("payroll.tax_config"))

    row = TaxInssBracket(effective_from=eff, up_to=up_to, rate=rate)
    db.session.add(row)
    db.session.commit()
    flash("Faixa INSS adicionada.", "success")
    return redirect(url_for("payroll.tax_config"))


@payroll_bp.post("/config/taxes/irrf_config")
@login_required
def tax_irrf_config_set():
    eff_raw = (request.form.get("effective_from") or "").strip()
    dep_raw = (request.form.get("dependent_deduction") or "").strip()
    eff = _parse_date(eff_raw)
    if not eff:
        flash("Vigência inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    dep = _to_decimal(dep_raw)
    if dep < 0:
        dep = Decimal("0")

    cfg = TaxIrrfConfig.query.filter_by(effective_from=eff).first()
    if not cfg:
        cfg = TaxIrrfConfig(effective_from=eff, dependent_deduction=dep)
        db.session.add(cfg)
    else:
        cfg.dependent_deduction = dep
    db.session.commit()
    flash("Config IRRF salva.", "success")
    return redirect(url_for("payroll.tax_config"))


@payroll_bp.post("/config/taxes/irrf")
@login_required
def tax_irrf_add():
    eff_raw = (request.form.get("effective_from") or "").strip()
    up_to_raw = (request.form.get("up_to") or "").strip()
    rate_raw = (request.form.get("rate") or "").strip()
    ded_raw = (request.form.get("deduction") or "").strip()
    eff = _parse_date(eff_raw)
    if not eff:
        flash("Vigência inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    up_to = _to_decimal(up_to_raw) if up_to_raw else None
    rate = _to_decimal(rate_raw)
    ded = _to_decimal(ded_raw)
    if rate < 0:
        flash("Alíquota inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    row = TaxIrrfBracket(effective_from=eff, up_to=up_to, rate=rate, deduction=ded)
    db.session.add(row)
    db.session.commit()
    flash("Faixa IRRF adicionada.", "success")
    return redirect(url_for("payroll.tax_config"))


@payroll_bp.get("/close")
@login_required
def close_home():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    comp = date(int(year), int(month), 1)
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)
    closed = CompetenceClose.query.filter_by(year=year, month=month).first()

    docs = {
        "darf": GuideDocument.query.filter_by(year=year, month=month, doc_type="darf").first(),
        "das": GuideDocument.query.filter_by(year=year, month=month, doc_type="das").first(),
        "fgts": GuideDocument.query.filter_by(year=year, month=month, doc_type="fgts").first(),
    }

    summary = _calc_month_summary(run)
    revenue_summary = _calc_revenue_month_summary(year, month)
    vacations_summary = _calc_vacations_month_summary(year, month)

    checklist = {
        "revenue": {
            "ok": bool(revenue_summary.get("count")),
            "title": "Receitas / notas do mês",
            "help": "Registre as notas (receitas) da competência. Isso serve para conferência, relatórios e cálculo do Fator R.",
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
            "action_label": "Registrar receitas",
        },
        "payroll": {
            "ok": bool(run),
            "title": "Folha do mês",
            "help": "Você precisa ter uma folha criada para esta competência, para gerar holerites e apurar valores.",
            "action_url": (url_for("payroll.payroll_home", year=year, month=month)),
            "action_label": "Abrir folha",
        },
        "taxes": {
            "ok": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
            "title": "Tabelas de INSS/IRRF",
            "help": "Essas tabelas são usadas para estimar descontos no holerite. Se estiver vazio, rode o sync ou configure manualmente.",
            "action_url": url_for("payroll.tax_config"),
            "action_label": "Ver configurações",
            "meta": {
                "inss_eff": inss_eff,
                "irrf_eff": irrf_eff,
            },
        },
        "guides": {
            "ok": all(bool(docs.get(k)) for k in ("darf", "das", "fgts")),
            "title": "Guias anexadas (DARF/DAS/FGTS)",
            "help": "Anexe os PDFs das guias da competência. Isso ajuda a centralizar e conferir antes de pagar.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Anexar guias",
        },
        "vacations": {
            "ok": True,
            "title": "Férias no mês",
            "help": "Se algum funcionário recebeu férias nesta competência, registre aqui para manter o histórico e conferir valores.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(vacations_summary.get("count") or 0),
                "total_gross": vacations_summary.get("total_gross"),
            },
        },
    }

    return render_template(
        "payroll/close_home.html",
        year=year,
        month=month,
        docs=docs,
        run=run,
        closed=closed,
        checklist=checklist,
        summary=summary,
        revenue_summary=revenue_summary,
        vacations_summary=vacations_summary,
    )


@payroll_bp.get("/revenue")
@login_required
def revenue_home():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)

    notes = RevenueNote.query.filter_by(year=year, month=month).order_by(RevenueNote.issued_at.asc().nullslast()).all()
    total = Decimal("0")
    for n in notes:
        try:
            total += Decimal(str(n.amount or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))

    return render_template(
        "payroll/revenue_home.html",
        year=year,
        month=month,
        notes=notes,
        total=total,
    )


@payroll_bp.post("/revenue")
@login_required
def revenue_add():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.revenue_home"))

    issued_at_raw = (request.form.get("issued_at") or "").strip()
    issued_at = _parse_date(issued_at_raw)

    customer_name = (request.form.get("customer_name") or "").strip()
    description = (request.form.get("description") or "").strip()
    amount = _to_decimal(request.form.get("amount"))
    if amount <= 0:
        flash("Informe um valor maior que zero.", "warning")
        return redirect(url_for("payroll.revenue_home", year=year, month=month))

    row = RevenueNote(
        year=year,
        month=month,
        issued_at=issued_at,
        customer_name=customer_name,
        description=description,
        amount=amount,
    )
    db.session.add(row)
    db.session.commit()

    flash("Receita registrada.", "success")
    return redirect(url_for("payroll.revenue_home", year=year, month=month))


@payroll_bp.post("/revenue/<int:note_id>/delete")
@login_required
def revenue_delete(note_id: int):
    row = RevenueNote.query.get_or_404(note_id)
    year = int(row.year)
    month = int(row.month)
    db.session.delete(row)
    db.session.commit()
    flash("Receita removida.", "success")
    return redirect(url_for("payroll.revenue_home", year=year, month=month))


@payroll_bp.post("/close/mark")
@login_required
def close_mark():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.close_home"))

    row = CompetenceClose.query.filter_by(year=year, month=month).first()
    if not row:
        row = CompetenceClose(year=year, month=month)
        db.session.add(row)
        db.session.commit()
    flash("Competência marcada como FECHADA (com aviso).", "success")
    return redirect(url_for("payroll.close_home", year=year, month=month))


@payroll_bp.post("/close/reopen")
@login_required
def close_reopen():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.close_home"))

    row = CompetenceClose.query.filter_by(year=year, month=month).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    flash("Competência reaberta.", "success")
    return redirect(url_for("payroll.close_home", year=year, month=month))


@payroll_bp.post("/close/upload")
@login_required
def close_upload():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    doc_type = (request.form.get("doc_type") or "").strip().lower()

    if _competence_is_closed(year, month):
        flash(
            "Atenção: esta competência está marcada como FECHADA. Você pode substituir o PDF, mas revise se o fechamento continua correto.",
            "warning",
        )

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.close_home"))

    if doc_type not in ("darf", "das", "fgts"):
        flash("Tipo de guia inválido.", "warning")
        return redirect(url_for("payroll.close_home", year=year, month=month))

    amount = _to_decimal(request.form.get("amount"))
    due_date_raw = (request.form.get("due_date") or "").strip()
    paid_at_raw = (request.form.get("paid_at") or "").strip()

    due_date = _parse_date(due_date_raw)
    paid_at = _parse_date(paid_at_raw)

    doc = GuideDocument.query.filter_by(year=year, month=month, doc_type=doc_type).first()
    if not doc:
        doc = GuideDocument(year=year, month=month, doc_type=doc_type, filename=None)
        db.session.add(doc)

    f = request.files.get("file")
    if f and f.filename:
        fname = secure_filename(f.filename)
        ext = os.path.splitext(fname)[1].lower()
        if ext != ".pdf":
            flash("Apenas PDF.", "warning")
            return redirect(url_for("payroll.close_home", year=year, month=month))

        target_name = f"{year}-{month:02d}_{doc_type}.pdf"
        target_path = os.path.join(_media_guides_dir(), target_name)
        f.save(target_path)
        doc.filename = target_name
    doc.amount = amount if amount > 0 else None
    doc.due_date = due_date
    doc.paid_at = paid_at

    db.session.commit()
    flash("Guia atualizada.", "success")
    return redirect(url_for("payroll.close_home", year=year, month=month))
