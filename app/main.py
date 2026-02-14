from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request, session, url_for
from flask_login import login_required, current_user

from .extensions import db
from .models import (
    CompetenceClose,
    EmployeeLeave,
    EmployeeTermination,
    EmployeeThirteenth,
    EmployeeVacation,
    GuideDocument,
    PayrollRun,
    RevenueNote,
    TaxInssBracket,
    TaxIrrfBracket,
    TaxIrrfConfig,
)


main_bp = Blueprint("main", __name__)


def _competence_start(year: int, month: int) -> date:
    return date(int(year), int(month), 1)


def _latest_inss_effective(effective_date: date):
    return (
        db.session.query(TaxInssBracket.effective_from)
        .filter(TaxInssBracket.effective_from <= effective_date)
        .order_by(TaxInssBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )


def _next_month(year: int, month: int) -> tuple[int, int]:
    if int(month) == 12:
        return int(year) + 1, 1
    return int(year), int(month) + 1


def _reminder_label(days_left: int | None, paid_at: date | None) -> str:
    if paid_at:
        return "Concluido"
    if days_left is None:
        return "Sem vencimento definido"
    if days_left < 0:
        return f"Atrasado ha {abs(days_left)} dia(s)"
    if days_left == 0:
        return "Vence hoje (D-0)"
    if days_left == 1:
        return "Vence amanha (D-1)"
    if days_left <= 3:
        return f"Prazo critico (D-{days_left})"
    if days_left <= 7:
        return f"Planejar esta semana (D-{days_left})"
    return f"No radar (D-{days_left})"


def _agenda_bucket(days_left: int | None, paid_at: date | None) -> str:
    if paid_at:
        return "done"
    if days_left is None:
        return "next_7_days"
    if days_left < 0:
        return "overdue"
    if days_left == 0:
        return "today"
    if days_left <= 7:
        return "next_7_days"
    return "later"


def _build_home_obligations(year: int, month: int, docs: dict[str, GuideDocument | None]) -> list[dict]:
    today = date.today()
    ny, nm = _next_month(year, month)
    default_due = date(int(ny), int(nm), 20)

    out: list[dict] = []
    for key, title in (
        ("das", "DAS"),
        ("fgts", "FGTS Digital"),
        ("darf", "DARF folha"),
    ):
        doc = docs.get(key)
        due_date = (getattr(doc, "due_date", None) if doc else None) or default_due
        paid_at = getattr(doc, "paid_at", None) if doc else None
        days_left = (due_date - today).days if due_date else None
        bucket = _agenda_bucket(days_left=days_left, paid_at=paid_at)
        out.append(
            {
                "key": key,
                "title": title,
                "due_date": due_date,
                "paid_at": paid_at,
                "days_left": days_left,
                "bucket": bucket,
                "reminder": _reminder_label(days_left=days_left, paid_at=paid_at),
                "action_url": url_for("payroll.close_home", year=year, month=month),
                "action_label": "Abrir fechamento",
            }
        )

    compliance_due = default_due - timedelta(days=2)
    compliance_days_left = (compliance_due - today).days
    compliance_bucket = _agenda_bucket(days_left=compliance_days_left, paid_at=None)
    out.append(
        {
            "key": "compliance",
            "title": "Compliance-check final",
            "due_date": compliance_due,
            "paid_at": None,
            "days_left": compliance_days_left,
            "bucket": compliance_bucket,
            "reminder": _reminder_label(days_left=compliance_days_left, paid_at=None),
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Abrir fechamento",
        }
    )

    out.sort(key=lambda x: (x.get("due_date") is None, x.get("due_date") or date.max))
    return out


def _latest_irrf_effective(effective_date: date):
    return (
        db.session.query(TaxIrrfBracket.effective_from)
        .filter(TaxIrrfBracket.effective_from <= effective_date)
        .order_by(TaxIrrfBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )


@main_bp.get("/")
@login_required
def index():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    if year < 2000:
        year = now.year
    if month < 1 or month > 12:
        month = now.month

    comp = _competence_start(year, month)
    run = PayrollRun.query.filter_by(year=year, month=month).first()
    revenue_count = RevenueNote.query.filter_by(year=year, month=month).count()

    inss_eff = _latest_inss_effective(comp)
    irrf_eff = _latest_irrf_effective(comp)
    irrf_cfg = (
        TaxIrrfConfig.query.filter(TaxIrrfConfig.effective_from <= comp)
        .order_by(TaxIrrfConfig.effective_from.desc())
        .first()
    )

    docs = {
        "darf": GuideDocument.query.filter_by(year=year, month=month, doc_type="darf").first(),
        "das": GuideDocument.query.filter_by(year=year, month=month, doc_type="das").first(),
        "fgts": GuideDocument.query.filter_by(year=year, month=month, doc_type="fgts").first(),
    }
    home_obligations = _build_home_obligations(year=year, month=month, docs=docs)
    overdue_items = [it for it in home_obligations if it.get("bucket") == "overdue"]
    today_items = [it for it in home_obligations if it.get("bucket") == "today"]
    next_7_items = [it for it in home_obligations if it.get("bucket") == "next_7_days"]

    proactive_action = None
    if today_items:
        proactive_action = today_items[0]
    elif overdue_items:
        proactive_action = overdue_items[0]

    last_compliance = session.get("payroll_last_compliance_check")
    weekly_summary = {
        "overdue_count": len(overdue_items),
        "next_7_days_count": len(next_7_items),
        "today_count": len(today_items),
        "last_compliance": last_compliance,
    }

    # Vacations summary for the month
    vac_rows = EmployeeVacation.query.filter_by(year=year, month=month).all()
    vac_count = len(vac_rows)
    vac_total = sum([Decimal(str(r.gross_total or 0)) for r in vac_rows], Decimal("0")).quantize(Decimal("0.01"))

    # 13th salary summary for the month
    thirteenth_rows = EmployeeThirteenth.query.filter_by(payment_year=year, payment_month=month).all()
    thirteenth_count = len(thirteenth_rows)
    thirteenth_total = sum([Decimal(str(r.gross_amount or 0)) for r in thirteenth_rows], Decimal("0")).quantize(Decimal("0.01"))

    # Terminations summary for the month
    termination_rows = EmployeeTermination.query.filter_by(year=year, month=month).all()
    termination_count = len(termination_rows)
    termination_total = sum([Decimal(str(r.gross_total or 0)) for r in termination_rows], Decimal("0")).quantize(Decimal("0.01"))

    # Leaves summary for the month
    leave_rows = EmployeeLeave.query.filter_by(year=year, month=month).all()
    leave_count = len(leave_rows)

    closed = CompetenceClose.query.filter_by(year=year, month=month).first()

    status = {
        "competence": {
            "year": year,
            "month": month,
            "closed": bool(closed),
        },
        "revenue": {
            "ok": revenue_count > 0,
            "count": revenue_count,
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
        },
        "payroll": {
            "ok": bool(run),
            "action_url": url_for("payroll.payroll_home", year=year, month=month),
        },
        "taxes": {
            "ok": bool(inss_eff) and bool(irrf_eff) and bool(irrf_cfg),
            "inss_eff": inss_eff,
            "irrf_eff": irrf_eff,
            "action_url": url_for("payroll.tax_config"),
        },
        "guides": {
            "ok": all(bool(docs.get(k)) and bool(getattr(docs.get(k), "filename", None)) for k in ("darf", "das", "fgts")),
            "docs": docs,
            "action_url": url_for("payroll.close_home", year=year, month=month),
        },
        "vacations": {
            "ok": True,  # Always OK since no vacations is valid state
            "count": vac_count,
            "total_gross": vac_total,
            "action_url": url_for("payroll.employees"),
        },
        "thirteenth": {
            "ok": True,  # Always OK since no 13th is valid state
            "count": thirteenth_count,
            "total_gross": thirteenth_total,
            "action_url": url_for("payroll.employees"),
        },
        "terminations": {
            "ok": True,
            "count": termination_count,
            "total_gross": termination_total,
            "action_url": url_for("payroll.employees"),
        },
        "leaves": {
            "ok": True,
            "count": leave_count,
            "action_url": url_for("payroll.employees"),
        },
        "close": {
            "ok": bool(closed),
            "action_url": url_for("payroll.close_home", year=year, month=month),
        },
    }

    next_step = None
    if not status["revenue"]["ok"]:
        next_step = {
            "title": "Registrar receitas do mês",
            "help": "Comece registrando as notas/receitas. Isso ajuda relatórios e o cálculo do Fator R.",
            "url": status["revenue"]["action_url"],
            "label": "Abrir Receitas",
        }
    elif not status["payroll"]["ok"]:
        next_step = {
            "title": "Criar/abrir a folha do mês",
            "help": "Crie a folha para lançar horas extras, gerar holerites e conferir totais.",
            "url": status["payroll"]["action_url"],
            "label": "Abrir Folha",
        }
    elif not status["taxes"]["ok"]:
        next_step = {
            "title": "Configurar tabelas de INSS/IRRF",
            "help": "Sem tabelas, o sistema não consegue estimar descontos. Configure para conferência.",
            "url": status["taxes"]["action_url"],
            "label": "Config INSS/IRRF",
        }
    elif not status["guides"]["ok"]:
        next_step = {
            "title": "Registrar/anexar guias do mês",
            "help": "Centralize DAS/FGTS/DARF para conferir antes de pagar.",
            "url": status["guides"]["action_url"],
            "label": "Abrir Fechamento",
        }
    elif not status["close"]["ok"]:
        next_step = {
            "title": "Marcar competência como fechada",
            "help": "Quando estiver tudo conferido, marque como fechada para organização (com aviso).",
            "url": status["close"]["action_url"],
            "label": "Abrir Fechamento",
        }
    else:
        next_step = {
            "title": "Tudo certo",
            "help": "A competência parece completa. Se precisar, revise as guias e confira os valores.",
            "url": status["close"]["action_url"],
            "label": "Revisar Fechamento",
        }

    return render_template(
        "index.html",
        user=current_user,
        year=year,
        month=month,
        status=status,
        next_step=next_step,
        proactive_action=proactive_action,
        overdue_items=overdue_items,
        weekly_summary=weekly_summary,
    )
