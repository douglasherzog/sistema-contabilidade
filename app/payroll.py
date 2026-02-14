from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from lxml import etree
from werkzeug.utils import secure_filename

from .extensions import db
from .models import (
    Company,
    CompetenceClose,
    EsocialSubmission,
    Employee,
    EmployeeDependent,
    EmployeeLeave,
    EmployeeSalary,
    EmployeeTermination,
    EmployeeThirteenth,
    EmployeeVacation,
    ComplianceEvidenceEvent,
    GuideDocument,
    RevenueNote,
    PayrollLine,
    PayrollRun,
    TaxInssBracket,
    TaxIrrfBracket,
    TaxIrrfConfig,
)
from .tax_sync import run_compliance_check, run_tax_sync


payroll_bp = Blueprint("payroll", __name__, url_prefix="/payroll")


TUTORIALS: dict[str, dict] = {
    "operacao_mensal_lavanderia": {
        "title": "Operação mensal da lavanderia (passo a passo)",
        "goal": "Executar todo mês sem esquecer etapas críticas: folha, guias, pagamento e fechamento.",
        "first_step": "Abra o Modo Guiado do mês e comece pela etapa 0 (cadastro oficial da empresa).",
        "version": "v1.2",
        "last_review": "2026-02-14",
        "today_actions": [
            "Abra o Modo Guiado na competência correta (ano/mês) e siga o 'Próximo passo recomendado'.",
            "Confirme pendências críticas do dia: folha para salvar, guia para pagar, comprovante para anexar.",
            "Antes de encerrar o dia, confira o Fechamento e deixe só itens realmente pendentes para amanhã.",
        ],
        "priority_actions": [
            {
                "label": "Hoje",
                "level": "danger",
                "items": [
                    "Siga o 'Próximo passo recomendado' do Modo Guiado.",
                    "Resolva itens críticos: folha pendente, guia vencendo e comprovante faltando.",
                ],
            },
            {
                "label": "Esta semana",
                "level": "warning",
                "items": [
                    "Conferir e salvar folha após atualizar salários e eventos trabalhistas.",
                    "Gerar guias oficiais nos portais e pagar dentro do prazo.",
                ],
            },
            {
                "label": "Até fechar o mês",
                "level": "success",
                "items": [
                    "Anexar PDF/recibo das guias pagas no sistema.",
                    "Revisar checklist do fechamento e marcar competência como fechada.",
                ],
            },
        ],
        "fields": [
            {"name": "Competência (ano/mês)", "explain": "Sempre confirme se está no mês correto antes de lançar dados."},
            {"name": "Checklist principal", "explain": "Use o Modo Guiado como roteiro fixo, na ordem apresentada."},
            {"name": "Guias e comprovantes", "explain": "Depois de pagar no portal oficial, anexe PDF/recibo no sistema."},
            {"name": "Fechamento", "explain": "Feche apenas quando tudo estiver conferido e anexado."},
        ],
        "steps": [
            "Abra o Modo Guiado e selecione ano/mês da competência.",
            "Etapa 0: confira o cadastro oficial da empresa (CNPJ, regime, classTrib e responsável).",
            "Etapa 1: atualize funcionários, salários e eventos (férias, 13º, rescisão, afastamento).",
            "Etapa 2: lance as receitas/notas da competência.",
            "Etapa 3: abra/salve a folha mensal e confira holerites.",
            "Etapa 4: confira/sincronize tabelas INSS e IRRF para o mês.",
            "Etapa 5: gere as guias nos portais oficiais, pague e anexe os PDFs/comprovantes no sistema.",
            "Etapa 6: revise o Fechamento e marque competência como fechada.",
            "Se algo estiver inconsistente, reabra a competência, ajuste e feche novamente.",
        ],
        "emergency_checks": [
            "Esqueci de pagar uma guia: gere/pague imediatamente no portal oficial, anexe o comprovante no sistema e registre observação no fechamento.",
            "Lancei receita no mês errado: corrija a receita na competência correta e revise o fechamento dos dois meses antes de fechar.",
            "Folha ficou com valor estranho: confira salário vigente, horas extras e tabelas INSS/IRRF; salve novamente e revise holerite.",
            "Fechei a competência com pendência: clique em 'Reabrir competência', ajuste os itens faltantes e feche novamente.",
            "Enviei eSocial com erro: gere novo XML corrigido, valide no XSD e registre protocolo correto da nova tentativa.",
            "Não sei qual é o próximo passo: volte para o Modo Guiado e siga o card 'Próximo passo recomendado'.",
        ],
    },
    "painel": {
        "title": "Painel do mês (Início)",
        "goal": "Entender o que fazer primeiro na competência e quais pendências existem.",
        "first_step": "Confira o card 'Próximo passo sugerido' e clique no botão indicado.",
        "fields": [
            {"name": "Ano", "explain": "Competência que você quer revisar (ex.: 2026)."},
            {"name": "Mês", "explain": "Mês da competência (1 a 12)."},
        ],
        "steps": [
            "Abra a competência correta no topo da tela.",
            "Siga a ordem sugerida pelo sistema: Receitas -> Folha -> Tabelas -> Fechamento.",
            "Use os cards de Férias/13º/Rescisões/Afastamentos para registrar eventos do mês.",
        ],
    },
    "empresa_oficial": {
        "title": "Cadastro oficial da empresa",
        "goal": "Preencher o mínimo oficial para habilitar integração assistida com eSocial.",
        "first_step": "Preencha CNPJ, regime, classTrib e dados do responsável legal.",
        "fields": [
            {"name": "CNPJ e CNAE", "explain": "Base cadastral da empresa/estabelecimento."},
            {"name": "Regime e classTrib", "explain": "Regras tributárias para eventos oficiais."},
            {"name": "Responsável", "explain": "Nome, CPF e e-mail para rastreabilidade eSocial."},
        ],
        "steps": [
            "Preencha os campos obrigatórios e salve.",
            "Conferir checklist de prontidão oficial na própria tela.",
            "Gerar XML S-1000/S-1005 no modo assistido e registrar protocolo manual.",
        ],
    },
    "modo_guiado": {
        "title": "Modo Guiado do Mês",
        "goal": "Executar a competência na ordem correta, sem esquecer etapas.",
        "first_step": "Abra o mês/ano e siga o 'Próximo passo' indicado pelo sistema.",
        "fields": [
            {"name": "Ano e mês", "explain": "Competência que você quer concluir."},
            {"name": "Checklist por etapa", "explain": "Mostra o que já foi feito e o que está pendente."},
            {"name": "Próximo passo", "explain": "Botão direto para a próxima tela recomendada."},
        ],
        "steps": [
            "Etapa 0: valide cadastro oficial da empresa.",
            "Cadastre/atualize funcionários e dados base.",
            "Registre receitas do mês.",
            "Abra e salve a folha mensal.",
            "Confira tabelas INSS/IRRF.",
            "Gere/pague guias oficiais e anexe comprovantes (DARF/DAS/FGTS).",
            "Só então marque competência como fechada.",
        ],
    },
    "funcionarios": {
        "title": "Funcionários",
        "goal": "Cadastrar e organizar funcionários que entram na folha.",
        "first_step": "Cadastre o funcionário antes de tentar lançar folha, férias ou 13º.",
        "fields": [
            {"name": "Nome", "explain": "Nome completo do funcionário."},
            {"name": "CPF", "explain": "Obrigatório no cadastro oficial mínimo."},
            {"name": "Nascimento", "explain": "Data de nascimento (dd/mm/aaaa)."},
            {"name": "Admissão", "explain": "Data de contratação (dd/mm/aaaa)."},
            {"name": "Cargo/Função", "explain": "Função principal do colaborador."},
        ],
        "steps": [
            "Clique em 'Cadastrar funcionário'.",
            "Abra o funcionário e cadastre salário por vigência.",
            "Cadastre dependentes para cálculo de IRRF.",
        ],
    },
    "funcionario": {
        "title": "Detalhe do funcionário",
        "goal": "Centralizar dados do funcionário e acessar módulos trabalhistas.",
        "first_step": "Cadastre salário vigente antes de registrar eventos (férias/13º/rescisão).",
        "fields": [
            {"name": "Vigência do salário", "explain": "Data a partir da qual o salário base vale."},
            {"name": "Salário base", "explain": "Valor mensal bruto do funcionário."},
            {"name": "Dependentes", "explain": "Usado para dedução de IRRF."},
        ],
        "steps": [
            "Atualize salário sempre que houver reajuste.",
            "Use os botões de Férias, 13º, Rescisão e Afastamentos para registros legais.",
        ],
    },
    "folha_home": {
        "title": "Folha (abertura da competência)",
        "goal": "Criar ou abrir a folha mensal.",
        "first_step": "Selecione ano/mês e clique em 'Abrir folha'.",
        "fields": [
            {"name": "Ano e Mês", "explain": "Competência da folha."},
        ],
        "steps": [
            "Se já existir folha, o sistema abre para edição.",
            "Se não existir, cria automaticamente com funcionários ativos.",
        ],
    },
    "folha_edicao": {
        "title": "Folha (edição)",
        "goal": "Lançar horas extras e gerar holerites.",
        "first_step": "Preencha jornada semanal e adicional; depois informe as horas extras por funcionário.",
        "fields": [
            {"name": "Jornada semanal", "explain": "Carga horária contratual da competência (ex.: 44,00)."},
            {"name": "Adicional hora extra", "explain": "Percentual aplicado sobre a hora normal (ex.: 50,00)."},
            {"name": "Horas extras por funcionário", "explain": "Quantidade no mês (aceita decimal)."},
        ],
        "steps": [
            "Informe jornada semanal e adicional no topo da tela.",
            "Preencha as horas extras por funcionário.",
            "Clique em salvar para recalcular automaticamente valor/hora extra, total bruto e holerite.",
        ],
    },
    "ferias": {
        "title": "Férias",
        "goal": "Registrar férias e abono com cálculo didático para conferência.",
        "first_step": "Abra a competência do pagamento e informe início/gozo corretamente.",
        "fields": [
            {"name": "Início do gozo", "explain": "Data que inicia o período de férias."},
            {"name": "Data do pagamento", "explain": "Opcional, mas importante para compliance."},
            {"name": "Dias de gozo", "explain": "Quantidade de dias de férias usufruídos."},
            {"name": "Dias vendidos", "explain": "Abono pecuniário (0 a 10 dias)."},
        ],
        "steps": [
            "Registre férias respeitando limite de 30 dias totais (gozo + venda).",
            "Abra o recibo e confira valores e estimativas.",
            "Veja o impacto no Fechamento do mês.",
        ],
    },
    "decimo": {
        "title": "13º salário",
        "goal": "Registrar parcelas do 13º conforme CLT.",
        "first_step": "Defina tipo correto (1ª, 2ª ou integral) e meses trabalhados.",
        "fields": [
            {"name": "Ano de referência", "explain": "Ano-base do 13º."},
            {"name": "Data do pagamento", "explain": "Data efetiva do pagamento."},
            {"name": "Meses trabalhados", "explain": "Proporcionalidade (1 a 12)."},
            {"name": "Tipo", "explain": "1ª parcela, 2ª parcela ou integral."},
        ],
        "steps": [
            "1ª parcela preferencialmente em novembro.",
            "2ª parcela até 20/12 (com descontos).",
            "Valide avisos CLT no recibo.",
        ],
    },
    "rescisao": {
        "title": "Rescisão",
        "goal": "Registrar desligamento com aviso prévio e conferência de multa FGTS.",
        "first_step": "Escolha o tipo de rescisão correto e informe aviso prévio.",
        "fields": [
            {"name": "Data da rescisão", "explain": "Data oficial de desligamento."},
            {"name": "Tipo", "explain": "Sem justa causa, com justa causa, acordo ou pedido de demissão."},
            {"name": "Aviso prévio / dias", "explain": "Se foi trabalhado, indenizado ou não aplicável."},
            {"name": "Saldo FGTS estimado", "explain": "Base para cálculo de multa FGTS."},
            {"name": "Alíquota multa FGTS", "explain": "40% sem justa causa, 20% acordo, 0% demais casos (regra simplificada)."},
        ],
        "steps": [
            "Preencha os dados e salve a rescisão.",
            "Abra o recibo e siga o checklist guiado (TRCT, FGTS, etc.).",
            "Confira alertas no compliance-check.",
        ],
    },
    "afastamentos": {
        "title": "Afastamentos",
        "goal": "Registrar atestados/licenças e validar regras básicas.",
        "first_step": "Informe período completo (início e fim) sem inversão de datas.",
        "fields": [
            {"name": "Tipo", "explain": "Médico, maternidade, acidente, não remunerada, outro."},
            {"name": "Início / Fim", "explain": "Período do afastamento."},
            {"name": "Pagamento", "explain": "Empresa, INSS ou misto."},
        ],
        "steps": [
            "Registre o afastamento por competência.",
            "Para afastamento médico >15 dias, prefira INSS/misto quando aplicável.",
        ],
    },
    "receitas": {
        "title": "Receitas / Notas",
        "goal": "Registrar faturamento mensal para conferência e fechamento.",
        "first_step": "Abra a competência e cadastre cada nota/receita do mês.",
        "fields": [
            {"name": "Data", "explain": "Data da nota (opcional)."},
            {"name": "Cliente", "explain": "Nome do cliente (opcional)."},
            {"name": "Descrição", "explain": "Resumo do serviço."},
            {"name": "Valor", "explain": "Valor bruto da receita."},
        ],
        "steps": [
            "Registre todas as receitas do mês.",
            "Confira total no resumo da tela.",
            "Valide no Fechamento se o item de receitas ficou OK.",
        ],
    },
    "fechamento": {
        "title": "Fechamento",
        "goal": "Conferir checklist completo antes de encerrar competência.",
        "first_step": "Revise os cards pendentes e abra cada ação sugerida.",
        "fields": [
            {"name": "Checklist guiado", "explain": "Mostra o que falta por área e direciona para a tela certa."},
            {"name": "Resumo do mês", "explain": "Conferência final dos totais estimados."},
        ],
        "steps": [
            "Verifique receitas, folha, tabelas, eventos trabalhistas e guias.",
            "Só depois marque competência como fechada.",
        ],
    },
    "tabelas": {
        "title": "Config INSS/IRRF",
        "goal": "Manter tabelas fiscais para cálculos estimados consistentes.",
        "first_step": "Atualize vigências e faixas do ano corrente antes de fechar competência.",
        "fields": [
            {"name": "Vigência", "explain": "Data de início da tabela."},
            {"name": "Faixa até", "explain": "Limite superior da faixa (vazio = última faixa)."},
            {"name": "Alíquota", "explain": "Percentual em decimal (ex.: 0,075)."},
            {"name": "Dedução IRRF", "explain": "Dedução por dependente e parcela a deduzir."},
        ],
        "steps": [
            "Use o bloco 'Sincronização oficial' para executar dry-run e aplicar tabelas diretamente na tela.",
            "Se necessário, ajuste manualmente e reconfira no holerite/fechamento.",
        ],
    },
}


@payroll_bp.get("/help")
@login_required
def help_index():
    return render_template("payroll/help_index.html", tutorials=TUTORIALS)


@payroll_bp.get("/help/<slug>")
@login_required
def help_page(slug: str):
    item = TUTORIALS.get(slug)
    if not item:
        flash("Tutorial não encontrado.", "warning")
        return redirect(url_for("payroll.help_index"))
    return render_template("payroll/help_page.html", slug=slug, item=item)


def _guide_step_keys() -> set[str]:
    return {"company_profile", "employees", "revenue", "payroll", "taxes", "guides", "close"}


def _guide_session_key(year: int, month: int) -> str:
    return f"payroll_guide_done:{int(year)}-{int(month)}"


@payroll_bp.post("/guide/step")
@login_required
def monthly_guide_step_toggle():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    step_key = (request.form.get("step_key") or "").strip().lower()
    action = (request.form.get("action") or "").strip().lower()

    if year < 2000 or month < 1 or month > 12 or step_key not in _guide_step_keys() or action not in {"done", "undone"}:
        flash("Ação do modo guiado inválida.", "warning")
        return redirect(url_for("payroll.monthly_guide"))

    s_key = _guide_session_key(year, month)
    done = set(session.get(s_key, []))

    if action == "done":
        done.add(step_key)
    elif step_key in done:
        done.remove(step_key)

    session[s_key] = sorted(done)
    flash("Progresso do modo guiado atualizado.", "success")
    return redirect(url_for("payroll.monthly_guide", year=year, month=month))


@payroll_bp.post("/guide/reset")
@login_required
def monthly_guide_reset():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.monthly_guide"))

    session.pop(_guide_session_key(year, month), None)
    flash("Marcação manual do modo guiado foi resetada para esta competência.", "success")
    return redirect(url_for("payroll.monthly_guide", year=year, month=month))


@payroll_bp.get("/guide")
@login_required
def monthly_guide():
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

    employees_count = Employee.query.count()
    active_employees_count = Employee.query.filter_by(active=True).count()
    revenue_summary = _calc_revenue_month_summary(year, month)
    vacations_summary = _calc_vacations_month_summary(year, month)
    thirteenth_summary = _calc_thirteenth_month_summary(year, month)
    terminations_summary = _calc_terminations_month_summary(year, month)
    leaves_summary = _calc_leaves_month_summary(year, month)

    company = _company_row()
    company_readiness = _company_official_readiness(company)

    steps = [
        {
            "key": "company_profile",
            "title": "0) Cadastro oficial da empresa",
            "auto_done": company_readiness.get("ok", False),
            "desc": "Configure CNPJ, classTrib, regime tributário e responsável legal antes de operar.",
            "action_url": url_for("payroll.company_profile"),
            "action_label": "Completar cadastro",
        },
        {
            "key": "employees",
            "title": "1) Base de funcionários",
            "auto_done": employees_count > 0 and active_employees_count > 0,
            "desc": "Tenha pelo menos 1 funcionário ativo com dados cadastrais e salário em dia.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Abrir funcionários",
        },
        {
            "key": "revenue",
            "title": "2) Receitas da competência",
            "auto_done": bool(revenue_summary.get("count")),
            "desc": "Registre as notas/receitas do mês para conferência financeira.",
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
            "action_label": "Lançar receitas",
        },
        {
            "key": "payroll",
            "title": "3) Folha mensal",
            "auto_done": bool(run),
            "desc": "Crie/abra a folha do mês e salve os lançamentos de horas extras.",
            "action_url": url_for("payroll.payroll_home", year=year, month=month),
            "action_label": "Abrir folha",
        },
        {
            "key": "taxes",
            "title": "4) Tabelas INSS/IRRF",
            "auto_done": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
            "desc": "Confirme as tabelas fiscais vigentes para estimativas coerentes.",
            "action_url": url_for("payroll.tax_config"),
            "action_label": "Conferir tabelas",
        },
        {
            "key": "guides",
            "title": "5) Guias da competência",
            "auto_done": all(bool(docs.get(k)) for k in ("darf", "das", "fgts")),
            "desc": "Anexe os PDFs de DARF, DAS e FGTS para centralizar conferência.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Anexar guias",
        },
        {
            "key": "close",
            "title": "6) Encerramento do mês",
            "auto_done": bool(closed),
            "desc": "Depois de tudo conferido, marque a competência como fechada.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Ir para fechamento",
        },
    ]

    reviewed_steps = set(session.get(_guide_session_key(year, month), []))
    for s in steps:
        s["manual_done"] = s["key"] in reviewed_steps
        s["done"] = bool(s.get("auto_done")) or bool(s.get("manual_done"))

    total_steps = len(steps)
    done_steps = sum(1 for s in steps if s.get("done"))
    progress_pct = int((done_steps * 100) / total_steps) if total_steps else 0

    next_step = next((s for s in steps if not s.get("done")), None)

    return render_template(
        "payroll/monthly_guide.html",
        year=year,
        month=month,
        steps=steps,
        next_step=next_step,
        total_steps=total_steps,
        done_steps=done_steps,
        progress_pct=progress_pct,
        employees_count=employees_count,
        active_employees_count=active_employees_count,
        revenue_summary=revenue_summary,
        vacations_summary=vacations_summary,
        thirteenth_summary=thirteenth_summary,
        terminations_summary=terminations_summary,
        leaves_summary=leaves_summary,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
    )


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


def _monthly_hours_from_weekly(weekly_hours: Decimal | None) -> Decimal:
    weekly = Decimal(str(weekly_hours or 0))
    if weekly <= 0:
        weekly = Decimal("44")
    return (weekly * Decimal("5")).quantize(Decimal("0.01"))


def _overtime_rate_from_salary(base_salary: Decimal | None, weekly_hours: Decimal | None, additional_pct: Decimal | None) -> Decimal:
    base = Decimal(str(base_salary or 0))
    month_hours = _monthly_hours_from_weekly(weekly_hours)
    additional = Decimal(str(additional_pct or 0))
    if additional < 0:
        additional = Decimal("0")
    if base <= 0 or month_hours <= 0:
        return Decimal("0")
    multiplier = Decimal("1") + (additional / Decimal("100"))
    return ((base / month_hours) * multiplier).quantize(Decimal("0.01"))


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


def _digits_only(v: str | None) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _is_valid_cpf(v: str | None) -> bool:
    cpf = _digits_only(v)
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False

    def _digit(base: str, factor: int) -> int:
        total = 0
        for n in base:
            total += int(n) * factor
            factor -= 1
        mod = total % 11
        return 0 if mod < 2 else 11 - mod

    d1 = _digit(cpf[:9], 10)
    d2 = _digit(cpf[:9] + str(d1), 11)
    return cpf[-2:] == f"{d1}{d2}"


def _is_valid_pis(v: str | None) -> bool:
    pis = _digits_only(v)
    if len(pis) != 11:
        return False
    if pis == pis[0] * 11:
        return False
    weights = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(pis[i]) * weights[i] for i in range(10))
    remainder = 11 - (total % 11)
    check = 0 if remainder in (10, 11) else remainder
    return check == int(pis[10])


def _validate_employee_official_minimum(
    *,
    full_name: str,
    cpf: str | None,
    birth_date: date | None,
    hired_at: date | None,
    role_title: str,
    pis: str | None,
    employee_id: int | None = None,
) -> list[str]:
    errors: list[str] = []
    if not full_name:
        errors.append("Informe o nome completo do funcionário.")
    if not cpf:
        errors.append("Informe o CPF (cadastro oficial mínimo).")
    elif not _is_valid_cpf(cpf):
        errors.append("CPF inválido. Verifique os 11 dígitos.")

    if not birth_date:
        errors.append("Informe a data de nascimento (cadastro oficial mínimo).")
    if not hired_at:
        errors.append("Informe a data de admissão (cadastro oficial mínimo).")
    if birth_date and hired_at and hired_at < birth_date:
        errors.append("Admissão não pode ser anterior à data de nascimento.")
    if not role_title:
        errors.append("Informe o cargo/função (cadastro oficial mínimo).")

    normalized_cpf = _digits_only(cpf) if cpf else None
    if normalized_cpf:
        q = Employee.query.filter(Employee.cpf == normalized_cpf)
        if employee_id:
            q = q.filter(Employee.id != int(employee_id))
        if q.first() is not None:
            errors.append("Já existe funcionário com este CPF.")

    normalized_pis = _digits_only(pis) if pis else None
    if normalized_pis:
        if not _is_valid_pis(normalized_pis):
            errors.append("PIS inválido. Verifique os 11 dígitos.")
        q = Employee.query.filter(Employee.pis == normalized_pis)
        if employee_id:
            q = q.filter(Employee.id != int(employee_id))
        if q.first() is not None:
            errors.append("Já existe funcionário com este PIS.")

    return errors


def _media_guides_dir() -> str:
    p = os.path.join(current_app.instance_path, "media", "guides")
    os.makedirs(p, exist_ok=True)
    return p


def _media_esocial_dir() -> str:
    p = os.path.join(current_app.instance_path, "media", "esocial")
    os.makedirs(p, exist_ok=True)
    return p


def _add_evidence_event(
    *,
    year: int,
    month: int,
    event_type: str,
    entity_type: str = "competence",
    entity_key: str | None = None,
    details: str | None = None,
) -> None:
    actor_email = getattr(current_user, "email", None)
    db.session.add(
        ComplianceEvidenceEvent(
            year=int(year),
            month=int(month),
            event_type=event_type,
            entity_type=entity_type,
            entity_key=entity_key,
            actor_email=actor_email,
            details=details,
        )
    )


def _validate_guide_document(
    *,
    doc: GuideDocument,
    year: int,
    month: int,
    doc_type: str,
) -> dict:
    warnings: list[str] = []
    dangers: list[str] = []

    expected_name = f"{int(year)}-{int(month):02d}_{doc_type}.pdf"
    filename = (getattr(doc, "filename", None) or "").strip()
    if not filename:
        dangers.append("PDF não anexado.")
    elif filename != expected_name:
        warnings.append("Nome do PDF fora do padrão da competência.")

    amount = Decimal(str(getattr(doc, "amount", 0) or 0))
    if amount <= 0:
        warnings.append("Valor da guia não informado.")

    due_date = getattr(doc, "due_date", None)
    paid_at = getattr(doc, "paid_at", None)
    if not due_date:
        warnings.append("Vencimento não informado.")
    if paid_at and due_date and paid_at > due_date:
        warnings.append("Pagamento após o vencimento (possível multa/juros).")

    if dangers:
        status = "danger"
    elif warnings:
        status = "warning"
    elif filename:
        status = "ok"
    else:
        status = "pending"

    summary = "Validação automática básica OK."
    if dangers:
        summary = dangers[0]
    elif warnings:
        summary = warnings[0]

    return {
        "status": status,
        "summary": summary,
        "warnings": warnings,
        "dangers": dangers,
    }


def _is_valid_cnpj(v: str | None) -> bool:
    cnpj = _digits_only(v)
    if len(cnpj) != 14:
        return False
    if cnpj == cnpj[0] * 14:
        return False

    def _digit(base: str, weights: list[int]) -> int:
        total = sum(int(base[i]) * weights[i] for i in range(len(weights)))
        mod = total % 11
        return 0 if mod < 2 else 11 - mod

    d1 = _digit(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _digit(cnpj[:12] + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return cnpj[-2:] == f"{d1}{d2}"


def _company_row() -> Company:
    row = Company.query.order_by(Company.id.asc()).first()
    if row:
        return row
    row = Company()
    db.session.add(row)
    db.session.commit()
    return row


def _validate_company_official_minimum(payload: dict) -> list[str]:
    errors: list[str] = []

    cnpj = payload.get("cnpj")
    if not cnpj:
        errors.append("Informe o CNPJ da empresa.")
    elif not _is_valid_cnpj(cnpj):
        errors.append("CNPJ inválido. Verifique os 14 dígitos.")

    if not payload.get("legal_name"):
        errors.append("Informe a razão social.")
    if not payload.get("cnae"):
        errors.append("Informe o CNAE principal.")
    if payload.get("tax_regime") not in {"simples", "presumido", "real"}:
        errors.append("Selecione um regime tributário válido.")
    if not payload.get("esocial_classification"):
        errors.append("Informe a classificação tributária eSocial (classTrib).")
    if payload.get("company_size") not in {"micro", "small", "medium", "large"}:
        errors.append("Selecione o porte da empresa.")
    if not payload.get("city") or not payload.get("state"):
        errors.append("Informe cidade e UF.")
    elif len((payload.get("state") or "").strip()) != 2:
        errors.append("UF deve conter 2 letras (ex.: RS).")

    if not payload.get("responsible_name"):
        errors.append("Informe o responsável legal.")
    resp_cpf = payload.get("responsible_cpf")
    if not resp_cpf:
        errors.append("Informe o CPF do responsável legal.")
    elif not _is_valid_cpf(resp_cpf):
        errors.append("CPF do responsável inválido.")

    resp_email = (payload.get("responsible_email") or "").strip()
    if not resp_email or "@" not in resp_email:
        errors.append("Informe um e-mail válido do responsável.")

    est_cnpj = payload.get("establishment_cnpj")
    if est_cnpj and not _is_valid_cnpj(est_cnpj):
        errors.append("CNPJ do estabelecimento inválido.")

    return errors


def _company_official_readiness(company: Company) -> dict:
    checks = [
        ("CNPJ válido", bool(company.cnpj) and _is_valid_cnpj(company.cnpj)),
        ("Razão social", bool((company.legal_name or "").strip())),
        ("CNAE principal", bool((company.cnae or "").strip())),
        ("Regime tributário", bool((company.tax_regime or "").strip())),
        ("classTrib eSocial", bool((company.esocial_classification or "").strip())),
        ("Porte da empresa", bool((company.company_size or "").strip())),
        ("Cidade/UF", bool((company.city or "").strip()) and bool((company.state or "").strip())),
        ("Responsável legal", bool((company.responsible_name or "").strip())),
        ("CPF do responsável", bool(company.responsible_cpf) and _is_valid_cpf(company.responsible_cpf)),
        ("E-mail do responsável", bool((company.responsible_email or "").strip()) and "@" in (company.responsible_email or "")),
    ]
    missing = [name for name, ok in checks if not ok]
    return {
        "ok": len(missing) == 0,
        "checks": [{"name": name, "ok": ok} for name, ok in checks],
        "missing": missing,
        "missing_count": len(missing),
    }


def _esocial_schema_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "schemas", "esocial", "v_s_01_03_00")


def _esocial_xsd_path(event_type: str) -> str | None:
    mapping = {
        "S-1000": "evtInfoEmpregador.xsd",
        "S-1005": "evtTabEstab.xsd",
    }
    name = mapping.get((event_type or "").upper())
    if not name:
        return None
    return os.path.join(_esocial_schema_dir(), name)


def _esocial_schema_readiness() -> dict:
    checks = []
    for event_type in ("S-1000", "S-1005"):
        p = _esocial_xsd_path(event_type)
        ok = bool(p and os.path.exists(p))
        checks.append({"event_type": event_type, "ok": ok, "path": p})
    return {
        "ok": all(row["ok"] for row in checks),
        "checks": checks,
    }


def _esocial_event_id() -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    tail = "".join(str(b % 10) for b in os.urandom(14))
    token = (stamp + tail)[:34]
    return f"ID{token}"


def _esocial_dummy_signature() -> str:
    return (
        "  <ds:Signature>\n"
        "    <ds:SignedInfo>\n"
        "      <ds:CanonicalizationMethod Algorithm=\"http://www.w3.org/TR/2001/REC-xml-c14n-20010315\"/>\n"
        "      <ds:SignatureMethod Algorithm=\"http://www.w3.org/2000/09/xmldsig#rsa-sha1\"/>\n"
        "      <ds:Reference URI=\"\">\n"
        "        <ds:DigestMethod Algorithm=\"http://www.w3.org/2000/09/xmldsig#sha1\"/>\n"
        "        <ds:DigestValue>AA==</ds:DigestValue>\n"
        "      </ds:Reference>\n"
        "    </ds:SignedInfo>\n"
        "    <ds:SignatureValue>AA==</ds:SignatureValue>\n"
        "  </ds:Signature>\n"
    )


def _validate_esocial_xml_xsd(event_type: str, xml_content: str) -> dict:
    xsd_path = _esocial_xsd_path(event_type)
    if not xsd_path or not os.path.exists(xsd_path):
        return {
            "status": "warning",
            "summary": "Schema XSD não localizado para o evento.",
            "errors": [f"Arquivo ausente: {xsd_path}"],
        }

    try:
        schema_doc = etree.parse(xsd_path)
        schema = etree.XMLSchema(schema_doc)
        xml_doc = etree.fromstring(xml_content.encode("utf-8"))
        valid = schema.validate(xml_doc)
        if valid:
            return {
                "status": "ok",
                "summary": "XML válido no XSD oficial.",
                "errors": [],
            }
        errors = [str(err.message) for err in schema.error_log][:5]
        return {
            "status": "danger",
            "summary": "XML inválido no XSD oficial.",
            "errors": errors,
        }
    except Exception as e:
        return {
            "status": "danger",
            "summary": "Falha técnica na validação XSD.",
            "errors": [str(e)],
        }


def _esocial_xml_s1000(company: Company) -> str:
    cnpj = xml_escape(company.cnpj or "")
    classtrib = xml_escape(company.esocial_classification or "")
    ind_porte = "S" if (company.company_size or "") in {"micro", "small"} else ""
    ini_valid = datetime.utcnow().strftime("%Y-%m")
    event_id = _esocial_event_id()

    ind_porte_xml = f"        <indPorte>{ind_porte}</indPorte>\n" if ind_porte else ""
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<eSocial xmlns=\"http://www.esocial.gov.br/schema/evt/evtInfoEmpregador/v_S_01_03_00\" xmlns:ds=\"http://www.w3.org/2000/09/xmldsig#\">\n"
        f"  <evtInfoEmpregador Id=\"{event_id}\">\n"
        "    <ideEvento>\n"
        "      <tpAmb>2</tpAmb>\n"
        "      <procEmi>1</procEmi>\n"
        "      <verProc>sistema-contabilidade-1.0</verProc>\n"
        "    </ideEvento>\n"
        "    <ideEmpregador>\n"
        "      <tpInsc>1</tpInsc>\n"
        f"      <nrInsc>{cnpj}</nrInsc>\n"
        "    </ideEmpregador>\n"
        "    <infoEmpregador>\n"
        "      <inclusao>\n"
        "        <idePeriodo>\n"
        f"          <iniValid>{ini_valid}</iniValid>\n"
        "        </idePeriodo>\n"
        "        <infoCadastro>\n"
        f"          <classTrib>{classtrib}</classTrib>\n"
        f"          <indDesFolha>{1 if company.payroll_tax_relief else 0}</indDesFolha>\n"
        f"          {ind_porte_xml}"
        "          <indOptRegEletron>1</indOptRegEletron>\n"
        "        </infoCadastro>\n"
        "      </inclusao>\n"
        "    </infoEmpregador>\n"
        "  </evtInfoEmpregador>\n"
        f"{_esocial_dummy_signature()}"
        "</eSocial>\n"
    )


def _esocial_xml_s1005(company: Company) -> str:
    cnpj_emp = xml_escape(company.cnpj or "")
    cnpj_est = xml_escape((company.establishment_cnpj or company.cnpj or "")[:14])
    cnae_est = xml_escape((_digits_only(company.establishment_cnae or company.cnae) or "")[:7])
    ini_valid = datetime.utcnow().strftime("%Y-%m")
    event_id = _esocial_event_id()
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<eSocial xmlns=\"http://www.esocial.gov.br/schema/evt/evtTabEstab/v_S_01_03_00\" xmlns:ds=\"http://www.w3.org/2000/09/xmldsig#\">\n"
        f"  <evtTabEstab Id=\"{event_id}\">\n"
        "    <ideEvento>\n"
        "      <tpAmb>2</tpAmb>\n"
        "      <procEmi>1</procEmi>\n"
        "      <verProc>sistema-contabilidade-1.0</verProc>\n"
        "    </ideEvento>\n"
        "    <ideEmpregador>\n"
        "      <tpInsc>1</tpInsc>\n"
        f"      <nrInsc>{cnpj_emp}</nrInsc>\n"
        "    </ideEmpregador>\n"
        "    <infoEstab>\n"
        "      <inclusao>\n"
        "        <ideEstab>\n"
        "          <tpInsc>1</tpInsc>\n"
        f"          <nrInsc>{cnpj_est}</nrInsc>\n"
        f"          <iniValid>{ini_valid}</iniValid>\n"
        "        </ideEstab>\n"
        "        <dadosEstab>\n"
        f"          <cnaePrep>{cnae_est}</cnaePrep>\n"
        "        </dadosEstab>\n"
        "      </inclusao>\n"
        "    </infoEstab>\n"
        "  </evtTabEstab>\n"
        f"{_esocial_dummy_signature()}"
        "</eSocial>\n"
    )


def _save_esocial_xml(event_type: str, xml_content: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"esocial_{event_type.lower()}_{stamp}.xml"
    path = os.path.join(_media_esocial_dir(), filename)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(xml_content)
    return filename


@payroll_bp.get("/company")
@login_required
def company_profile():
    company = _company_row()
    readiness = _company_official_readiness(company)
    return render_template("payroll/company_profile.html", company=company, readiness=readiness)


@payroll_bp.post("/company")
@login_required
def company_profile_save():
    company = _company_row()
    payload = {
        "legal_name": (request.form.get("legal_name") or "").strip(),
        "trade_name": (request.form.get("trade_name") or "").strip(),
        "cnpj": _digits_only(request.form.get("cnpj")) or "",
        "cnae": _digits_only(request.form.get("cnae")) or (request.form.get("cnae") or "").strip(),
        "tax_regime": (request.form.get("tax_regime") or "").strip(),
        "esocial_classification": (request.form.get("esocial_classification") or "").strip(),
        "company_size": (request.form.get("company_size") or "").strip(),
        "payroll_tax_relief": (request.form.get("payroll_tax_relief") or "0") == "1",
        "state_registration": (request.form.get("state_registration") or "").strip() or None,
        "municipal_registration": (request.form.get("municipal_registration") or "").strip() or None,
        "city": (request.form.get("city") or "").strip(),
        "state": (request.form.get("state") or "").strip().upper(),
        "responsible_name": (request.form.get("responsible_name") or "").strip(),
        "responsible_cpf": _digits_only(request.form.get("responsible_cpf")) or "",
        "responsible_email": (request.form.get("responsible_email") or "").strip(),
        "responsible_phone": (request.form.get("responsible_phone") or "").strip() or None,
        "establishment_cnpj": _digits_only(request.form.get("establishment_cnpj")) or None,
        "establishment_cnae": _digits_only(request.form.get("establishment_cnae")) or (request.form.get("establishment_cnae") or "").strip() or None,
    }
    errors = _validate_company_official_minimum(payload)
    if errors:
        for msg in errors:
            flash(msg, "warning")
        return redirect(url_for("payroll.company_profile"))

    for key, val in payload.items():
        setattr(company, key, val)
    now = datetime.utcnow()
    _add_evidence_event(
        year=now.year,
        month=now.month,
        event_type="company_profile_updated",
        details="Cadastro oficial mínimo da empresa atualizado",
    )
    db.session.commit()
    flash("Cadastro oficial mínimo da empresa salvo com sucesso.", "success")
    return redirect(url_for("payroll.company_profile"))


@payroll_bp.get("/esocial/assisted")
@login_required
def esocial_assisted_home():
    company = _company_row()
    readiness = _company_official_readiness(company)
    schema_readiness = _esocial_schema_readiness()
    submissions = EsocialSubmission.query.order_by(EsocialSubmission.created_at.desc()).limit(30).all()
    return render_template(
        "payroll/esocial_assisted.html",
        company=company,
        readiness=readiness,
        schema_readiness=schema_readiness,
        submissions=submissions,
    )


@payroll_bp.post("/esocial/assisted/generate")
@login_required
def esocial_assisted_generate():
    event_type = (request.form.get("event_type") or "").strip().upper()
    if event_type not in {"S-1000", "S-1005"}:
        flash("Evento inválido para geração assistida.", "warning")
        return redirect(url_for("payroll.esocial_assisted_home"))

    schema_readiness = _esocial_schema_readiness()
    if not schema_readiness.get("ok"):
        flash("Schemas XSD oficiais não encontrados no sistema. Reinstale os esquemas antes de gerar XML.", "warning")
        return redirect(url_for("payroll.esocial_assisted_home"))

    company = _company_row()
    readiness = _company_official_readiness(company)
    if not readiness.get("ok"):
        flash("Cadastro oficial da empresa incompleto. Complete os campos obrigatórios antes de gerar XML.", "warning")
        return redirect(url_for("payroll.company_profile"))

    xml = _esocial_xml_s1000(company) if event_type == "S-1000" else _esocial_xml_s1005(company)
    xsd_validation = _validate_esocial_xml_xsd(event_type=event_type, xml_content=xml)
    xml_filename = _save_esocial_xml(event_type=event_type, xml_content=xml)
    sub = EsocialSubmission(
        event_type=event_type,
        status=("generated" if xsd_validation.get("status") == "ok" else "error"),
        xml_filename=xml_filename,
        xsd_validation_status=xsd_validation.get("status") or "pending",
        xsd_validation_summary="; ".join(xsd_validation.get("errors") or [])[:500] if xsd_validation.get("errors") else xsd_validation.get("summary"),
        actor_email=getattr(current_user, "email", None),
        notes="Gerado em modo assistido para envio manual no portal oficial.",
    )
    db.session.add(sub)
    now = datetime.utcnow()
    _add_evidence_event(
        year=now.year,
        month=now.month,
        event_type="esocial_xml_generated",
        entity_type="guide",
        entity_key=event_type,
        details=f"xml={xml_filename} xsd={xsd_validation.get('status')}",
    )
    db.session.commit()
    if xsd_validation.get("status") == "ok":
        flash(f"XML {event_type} gerado e validado no XSD oficial. Faça o envio manual no ambiente oficial do eSocial.", "success")
    else:
        flash(f"XML {event_type} gerado, mas com alerta de validação XSD: {xsd_validation.get('summary')}", "warning")
    return redirect(url_for("payroll.esocial_assisted_home"))


@payroll_bp.post("/esocial/assisted/<int:submission_id>/mark-sent")
@login_required
def esocial_assisted_mark_sent(submission_id: int):
    sub = EsocialSubmission.query.get_or_404(submission_id)
    protocol = (request.form.get("protocol") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    if not protocol:
        flash("Informe o protocolo oficial para marcar como enviado.", "warning")
        return redirect(url_for("payroll.esocial_assisted_home"))
    sub.status = "sent"
    sub.protocol = protocol
    sub.notes = notes or sub.notes
    sub.sent_at = datetime.utcnow()
    sub.actor_email = getattr(current_user, "email", None)
    _add_evidence_event(
        year=int((sub.sent_at or datetime.utcnow()).year),
        month=int((sub.sent_at or datetime.utcnow()).month),
        event_type="esocial_manual_sent",
        entity_type="guide",
        entity_key=sub.event_type,
        details=f"protocol={protocol}",
    )
    db.session.commit()
    flash("Envio manual registrado com sucesso (trilha de evidência).", "success")
    return redirect(url_for("payroll.esocial_assisted_home"))


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


def _calc_terminations_month_summary(year: int, month: int) -> dict:
    rows = EmployeeTermination.query.filter_by(year=int(year), month=int(month)).all()
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


def _calc_leaves_month_summary(year: int, month: int) -> dict:
    rows = EmployeeLeave.query.filter_by(year=int(year), month=int(month)).all()
    return {
        "count": len(rows),
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
    cpf = _digits_only((request.form.get("cpf") or "").strip()) or None
    birth_date_raw = (request.form.get("birth_date") or "").strip()
    birth_date = _parse_date(birth_date_raw)
    hired_at_raw = (request.form.get("hired_at") or "").strip()
    hired_at = _parse_date(hired_at_raw)
    role_title = (request.form.get("role_title") or "").strip()
    pis = _digits_only((request.form.get("pis") or "").strip()) or None

    errors = _validate_employee_official_minimum(
        full_name=full_name,
        cpf=cpf,
        birth_date=birth_date,
        hired_at=hired_at,
        role_title=role_title,
        pis=pis,
    )
    if errors:
        for msg in errors:
            flash(msg, "warning")
        return redirect(url_for("payroll.employees"))

    e = Employee(
        full_name=full_name,
        cpf=cpf,
        birth_date=birth_date,
        hired_at=hired_at,
        role_title=role_title,
        pis=pis,
    )
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


@payroll_bp.post("/employees/<int:employee_id>/profile")
@login_required
def employee_update_profile(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    full_name = (request.form.get("full_name") or "").strip()
    cpf = _digits_only((request.form.get("cpf") or "").strip()) or None
    birth_date = _parse_date(request.form.get("birth_date"))
    hired_at = _parse_date(request.form.get("hired_at"))
    role_title = (request.form.get("role_title") or "").strip()
    pis = _digits_only((request.form.get("pis") or "").strip()) or None

    errors = _validate_employee_official_minimum(
        full_name=full_name,
        cpf=cpf,
        birth_date=birth_date,
        hired_at=hired_at,
        role_title=role_title,
        pis=pis,
        employee_id=e.id,
    )
    if errors:
        for msg in errors:
            flash(msg, "warning")
        return redirect(url_for("payroll.employee_detail", employee_id=e.id))

    e.full_name = full_name
    e.cpf = cpf
    e.birth_date = birth_date
    e.hired_at = hired_at
    e.role_title = role_title
    e.pis = pis
    db.session.commit()
    flash("Perfil do funcionário atualizado.", "success")
    return redirect(url_for("payroll.employee_detail", employee_id=e.id))


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


# =============================================================================
# 13º SALÁRIO (DECIMO TERCEIRO) - Conforme CLT
# =============================================================================

def _calc_thirteenth_amount(base_salary: Decimal, months_worked: int) -> dict:
    """Cálculo CLT: (salário / 12) × meses trabalhados."""
    m = max(1, min(12, int(months_worked or 12)))
    monthly_part = (base_salary / Decimal("12")).quantize(Decimal("0.01"))
    gross = (monthly_part * Decimal(str(m))).quantize(Decimal("0.01"))
    return {
        "monthly_part": monthly_part,
        "months_worked": m,
        "gross_amount": gross,
    }


def _termination_expected_fgts_rate(termination_type: str) -> Decimal:
    t = (termination_type or "").strip().lower()
    if t == "without_cause":
        return Decimal("0.40")
    if t == "agreement":
        return Decimal("0.20")
    return Decimal("0")


def _termination_guided_checklist(termination_type: str, notice_type: str) -> list[str]:
    t = (termination_type or "").strip().lower()
    n = (notice_type or "").strip().lower()
    items: list[str] = [
        "Conferir saldo de salário e férias (vencidas/proporcionais + 1/3).",
        "Emitir TRCT e termo de quitação para assinatura.",
        "Conferir lançamentos de eSocial/SEFIP/FGTS Digital conforme competência.",
    ]
    if t in ("without_cause", "agreement"):
        if n == "none":
            items.append("Definir aviso prévio (trabalhado ou indenizado) conforme CLT.")
        else:
            items.append(f"Aviso prévio informado: {n}.")
    if t == "without_cause":
        items.append("Aplicar multa de 40% do FGTS (quando houver saldo).")
        items.append("Gerar chave de conectividade e avaliar seguro-desemprego.")
    elif t == "agreement":
        items.append("Aplicar multa de 20% do FGTS (rescisão por acordo).")
    elif t == "with_cause":
        items.append("Sem aviso indenizado e sem multa FGTS (justa causa).")
    elif t == "resignation":
        items.append("Pedido de demissão: validar aviso prévio conforme política aplicável.")
    return items


def _calc_thirteenth_month_summary(year: int, month: int) -> dict:
    """Resumo de 13º registrados na competência."""
    rows = EmployeeThirteenth.query.filter_by(payment_year=int(year), payment_month=int(month)).all()
    total = Decimal("0")
    for r in rows:
        try:
            total += Decimal(str(r.gross_amount or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))
    return {
        "count": len(rows),
        "total_gross": total,
    }


@payroll_bp.get("/employees/<int:employee_id>/thirteenth")
@login_required
def employee_thirteenth(employee_id: int):
    """Tela de gestão do 13º salário por funcionário."""
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = EmployeeThirteenth.query.filter_by(employee_id=e.id).order_by(
        EmployeeThirteenth.reference_year.desc(),
        EmployeeThirteenth.payment_year.desc(),
        EmployeeThirteenth.payment_month.desc(),
    ).all()
    return render_template(
        "payroll/employee_thirteenth.html",
        e=e,
        year=year,
        month=month,
        rows=rows,
    )


@payroll_bp.post("/employees/<int:employee_id>/thirteenth")
@login_required
def employee_thirteenth_add(employee_id: int):
    """Cadastra pagamento de 13º (1ª parcela, 2ª parcela ou integral)."""
    e = Employee.query.get_or_404(employee_id)
    ref_year = int(request.form.get("reference_year") or 0)
    pay_year = int(request.form.get("payment_year") or 0)
    pay_month = int(request.form.get("payment_month") or 0)
    pay_date = _parse_date(request.form.get("pay_date"))
    months_worked = int(request.form.get("months_worked") or 12)
    payment_type = (request.form.get("payment_type") or "").strip().lower()

    if ref_year < 2000 or pay_year < 2000 or pay_month < 1 or pay_month > 12:
        flash("Datas inválidas.", "warning")
        return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id))

    if payment_type not in ("1st_installment", "2nd_installment", "full"):
        flash("Tipo de pagamento inválido.", "warning")
        return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id, year=pay_year, month=pay_month))

    if months_worked < 1 or months_worked > 12:
        flash("Meses trabalhados devem ser entre 1 e 12.", "warning")
        return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id, year=pay_year, month=pay_month))

    # Usa salário do mês de pagamento como base
    base_salary = _salary_for_employee(e, pay_year, pay_month)
    amounts = _calc_thirteenth_amount(base_salary, months_worked)

    # Estimativa de descontos apenas para 2ª parcela (conforme CLT)
    comp = _competence_start(pay_year, pay_month)
    deps_count = EmployeeDependent.query.filter_by(employee_id=e.id).count()
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    inss_est = None
    irrf_est = None
    net_est = None
    gross = amounts["gross_amount"]

    # CLT: descontos aplicam-se na 2ª parcela (ou no integral se for único pagamento)
    apply_discounts = payment_type in ("2nd_installment", "full")
    if apply_discounts and inss_rows:
        inss_est = _calc_inss_progressive(gross, inss_rows)
    if apply_discounts and irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)
    if inss_est is not None and irrf_est is not None:
        net_est = (gross - inss_est - irrf_est).quantize(Decimal("0.01"))

    row = EmployeeThirteenth(
        employee_id=e.id,
        reference_year=ref_year,
        payment_year=pay_year,
        payment_month=pay_month,
        payment_type=payment_type,
        pay_date=pay_date,
        base_salary_at_calc=base_salary,
        months_worked=amounts["months_worked"],
        gross_amount=amounts["gross_amount"],
        inss_est=inss_est,
        irrf_est=irrf_est,
        net_est=net_est,
    )
    db.session.add(row)
    db.session.commit()

    flash("13º salário registrado.", "success")
    return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id, year=pay_year, month=pay_month))


@payroll_bp.get("/thirteenth/<int:thirteenth_id>/receipt")
@login_required
def thirteenth_receipt(thirteenth_id: int):
    """Recibo imprimível do 13º salário."""
    t = EmployeeThirteenth.query.get_or_404(thirteenth_id)

    comp = _competence_start(int(t.payment_year), int(t.payment_month))
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    # CLT: avisos sobre prazos
    clt_warnings = []
    if t.payment_type == "1st_installment":
        if int(t.payment_month) != 11:
            clt_warnings.append("CLT: 1ª parcela idealmente paga em novembro.")
    elif t.payment_type == "2nd_installment":
        if int(t.payment_month) != 12:
            clt_warnings.append("CLT: 2ª parcela deve ser paga até 20 de dezembro.")

    return render_template(
        "payroll/thirteenth_receipt.html",
        t=t,
        employee=t.employee,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
        has_tables=bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
        clt_warnings=clt_warnings,
    )


@payroll_bp.get("/employees/<int:employee_id>/terminations")
@login_required
def employee_terminations(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = (
        EmployeeTermination.query.filter_by(employee_id=e.id)
        .order_by(EmployeeTermination.termination_date.desc(), EmployeeTermination.id.desc())
        .all()
    )
    return render_template("payroll/employee_terminations.html", e=e, year=year, month=month, rows=rows)


@payroll_bp.post("/employees/<int:employee_id>/terminations")
@login_required
def employee_terminations_add(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    termination_date = _parse_date(request.form.get("termination_date"))
    termination_type = (request.form.get("termination_type") or "").strip().lower()
    notice_type = (request.form.get("notice_type") or "none").strip().lower()
    notice_days = int(request.form.get("notice_days") or 0)
    reason = (request.form.get("reason") or "").strip() or None
    gross_total = _to_decimal(request.form.get("gross_total"))
    fgts_balance_est = _to_decimal(request.form.get("fgts_balance_est"), default=Decimal("0"))
    fgts_fine_rate_in = _to_decimal(request.form.get("fgts_fine_rate"), default=Decimal("-1"))

    if year < 2000 or month < 1 or month > 12 or not termination_date:
        flash("Dados da rescisão inválidos.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id))

    if termination_type not in ("without_cause", "with_cause", "agreement", "resignation"):
        flash("Tipo de rescisão inválido.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))
    if notice_type not in ("worked", "indemnified", "none"):
        flash("Tipo de aviso prévio inválido.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))
    if notice_days < 0 or notice_days > 120:
        flash("Dias de aviso prévio inválidos.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))

    inss_est = None
    irrf_est = None
    net_est = None
    comp = _competence_start(year, month)
    deps_count = EmployeeDependent.query.filter_by(employee_id=e.id).count()
    _inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    _irrf_eff, irrf_rows = _latest_irrf_brackets(comp)
    if gross_total > 0 and inss_rows:
        inss_est = _calc_inss_progressive(gross_total, inss_rows)
    if gross_total > 0 and irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross_total - inss_est, irrf_cfg, irrf_rows, deps_count)
    if inss_est is not None and irrf_est is not None:
        net_est = (gross_total - inss_est - irrf_est).quantize(Decimal("0.01"))

    expected_rate = _termination_expected_fgts_rate(termination_type)
    if fgts_fine_rate_in < 0:
        fgts_fine_rate = expected_rate
    else:
        fgts_fine_rate = fgts_fine_rate_in
    fgts_fine_est = None
    if fgts_balance_est > 0 and fgts_fine_rate > 0:
        fgts_fine_est = (fgts_balance_est * fgts_fine_rate).quantize(Decimal("0.01"))

    row = EmployeeTermination(
        employee_id=e.id,
        year=year,
        month=month,
        termination_date=termination_date,
        termination_type=termination_type,
        notice_type=notice_type,
        notice_days=notice_days,
        reason=reason,
        gross_total=gross_total,
        fgts_balance_est=fgts_balance_est,
        fgts_fine_rate=fgts_fine_rate,
        fgts_fine_est=fgts_fine_est,
        inss_est=inss_est,
        irrf_est=irrf_est,
        net_est=net_est,
    )
    # Employee is no longer active after termination record
    e.active = False
    db.session.add(row)
    db.session.add(e)
    db.session.commit()
    flash("Rescisão registrada e funcionário marcado como inativo.", "success")
    return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))


@payroll_bp.get("/terminations/<int:termination_id>/receipt")
@login_required
def termination_receipt(termination_id: int):
    t = EmployeeTermination.query.get_or_404(termination_id)
    checklist = _termination_guided_checklist(t.termination_type, t.notice_type)
    return render_template("payroll/termination_receipt.html", t=t, employee=t.employee, checklist=checklist)


@payroll_bp.get("/employees/<int:employee_id>/leaves")
@login_required
def employee_leaves(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = (
        EmployeeLeave.query.filter_by(employee_id=e.id)
        .order_by(EmployeeLeave.start_date.desc(), EmployeeLeave.id.desc())
        .all()
    )
    return render_template("payroll/employee_leaves.html", e=e, year=year, month=month, rows=rows)


@payroll_bp.post("/employees/<int:employee_id>/leaves")
@login_required
def employee_leaves_add(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    leave_type = (request.form.get("leave_type") or "").strip().lower()
    start_date = _parse_date(request.form.get("start_date"))
    end_date = _parse_date(request.form.get("end_date"))
    paid_by = (request.form.get("paid_by") or "").strip().lower()
    reason = (request.form.get("reason") or "").strip() or None

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id))
    if not start_date or not end_date or end_date < start_date:
        flash("Período do afastamento inválido.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))
    if leave_type not in ("medical", "maternity", "accident", "unpaid", "other"):
        flash("Tipo de afastamento inválido.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))
    if paid_by not in ("company", "inss", "mixed"):
        flash("Origem de pagamento inválida.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))

    row = EmployeeLeave(
        employee_id=e.id,
        year=year,
        month=month,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        paid_by=paid_by,
        reason=reason,
    )
    db.session.add(row)
    db.session.commit()
    flash("Afastamento registrado.", "success")
    return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))


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
        run = PayrollRun(
            year=year,
            month=month,
            overtime_hour_rate=Decimal("12.45"),
            overtime_weekly_hours=Decimal("44"),
            overtime_additional_pct=Decimal("50"),
        )
        db.session.add(run)
        db.session.flush()

        employees = Employee.query.filter_by(active=True).order_by(Employee.full_name.asc()).all()
        for e in employees:
            base = _salary_for_employee(e, year, month)
            line_rate = _overtime_rate_from_salary(base, run.overtime_weekly_hours, run.overtime_additional_pct)
            line = PayrollLine(
                payroll_run_id=run.id,
                employee_id=e.id,
                base_salary=base,
                overtime_hours=Decimal("0"),
                overtime_hour_rate=line_rate,
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
    monthly_hours = _monthly_hours_from_weekly(Decimal(str(run.overtime_weekly_hours or 44)))
    return render_template("payroll/payroll_edit.html", run=run, lines=lines, monthly_hours=monthly_hours)


@payroll_bp.post("/<int:run_id>")
@login_required
def payroll_save(run_id: int):
    run = PayrollRun.query.get_or_404(run_id)

    if _competence_is_closed(run.year, run.month):
        flash(
            "Atenção: esta competência está marcada como FECHADA. Você ainda pode alterar, mas revise os relatórios/guias para manter tudo consistente.",
            "warning",
        )

    weekly_hours = _to_decimal(
        request.form.get("overtime_weekly_hours"),
        default=Decimal(str(run.overtime_weekly_hours or 44)),
    )
    if weekly_hours <= 0:
        weekly_hours = Decimal("44")

    additional_pct = _to_decimal(
        request.form.get("overtime_additional_pct"),
        default=Decimal(str(run.overtime_additional_pct or 50)),
    )
    if additional_pct < 0:
        additional_pct = Decimal("0")

    run.overtime_weekly_hours = weekly_hours
    run.overtime_additional_pct = additional_pct

    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
    first_rate = None
    for ln in lines:
        key = f"overtime_hours_{ln.employee_id}"
        hours = _to_decimal(request.form.get(key), default=Decimal("0"))
        if hours < 0:
            hours = Decimal("0")
        rate = _overtime_rate_from_salary(ln.base_salary, run.overtime_weekly_hours, run.overtime_additional_pct)
        ln.overtime_hours = hours
        ln.overtime_hour_rate = rate
        ln.overtime_amount = (hours * rate).quantize(Decimal("0.01"))
        ln.gross_total = (Decimal(str(ln.base_salary)) + ln.overtime_amount).quantize(Decimal("0.01"))
        if first_rate is None:
            first_rate = rate
        db.session.add(ln)

    run.overtime_hour_rate = first_rate if first_rate is not None else Decimal("0")

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
    context = _tax_config_context()
    return render_template("payroll/tax_config.html", **context)


def _tax_config_context() -> dict:
    inss_rows = TaxInssBracket.query.order_by(TaxInssBracket.effective_from.desc(), TaxInssBracket.up_to.asc().nullslast()).all()
    irrf_rows = TaxIrrfBracket.query.order_by(TaxIrrfBracket.effective_from.desc(), TaxIrrfBracket.up_to.asc().nullslast()).all()
    irrf_configs = TaxIrrfConfig.query.order_by(TaxIrrfConfig.effective_from.desc()).all()
    return {
        "inss_rows": inss_rows,
        "irrf_rows": irrf_rows,
        "irrf_configs": irrf_configs,
    }


@payroll_bp.post("/config/taxes/sync")
@login_required
def tax_sync_trigger():
    try:
        target_year = int(request.form.get("target_year") or date.today().year)
    except (TypeError, ValueError):
        target_year = 0
    mode = (request.form.get("mode") or "dry_run").strip().lower()
    apply_changes = mode == "apply"

    if target_year < 2000 or target_year > 9999:
        flash("Ano inválido para sincronização fiscal.", "warning")
        context = _tax_config_context()
        return render_template("payroll/tax_config.html", **context, sync_result=None)

    sync_result = None
    try:
        sync_result = run_tax_sync(target_year=target_year, apply_changes=apply_changes)
        if sync_result.get("applied"):
            flash("Sincronização concluída e tabelas fiscais gravadas no banco.", "success")
        else:
            flash("Simulação concluída (dry-run). Revise o relatório antes de aplicar.", "info")
    except Exception as e:
        flash(f"Falha na sincronização fiscal: {e}", "warning")
        sync_result = {
            "target_year": target_year,
            "applied": False,
            "report_lines": [f"ERRO: {e}"],
        }

    context = _tax_config_context()
    return render_template("payroll/tax_config.html", **context, sync_result=sync_result)


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


def _next_month(year: int, month: int) -> tuple[int, int]:
    if int(month) == 12:
        return int(year) + 1, 1
    return int(year), int(month) + 1


def _deadline_status(today: date, due_date: date | None, paid_at: date | None) -> str:
    if paid_at:
        return "ok"
    if due_date is None:
        return "pending"
    days_left = (due_date - today).days
    if days_left < 0:
        return "danger"
    if days_left <= 3:
        return "warning"
    return "ok"


def _build_legal_deadlines(year: int, month: int, docs: dict[str, GuideDocument | None]) -> list[dict]:
    today = date.today()
    ny, nm = _next_month(year, month)
    default_due = date(int(ny), int(nm), 20)

    items = [
        {
            "key": "das",
            "title": "DAS (Simples Nacional)",
            "source": "Prazo operacional padrão: dia 20 do mês seguinte (confira a guia oficial).",
        },
        {
            "key": "fgts",
            "title": "FGTS Digital",
            "source": "Prazo operacional padrão: dia 20 do mês seguinte (confira a guia oficial).",
        },
        {
            "key": "darf",
            "title": "DARF (encargos folha)",
            "source": "Prazo operacional padrão: dia 20 do mês seguinte (confira a guia oficial).",
        },
    ]

    out: list[dict] = []
    for item in items:
        doc = docs.get(item["key"])
        due_date = (getattr(doc, "due_date", None) if doc else None) or default_due
        paid_at = getattr(doc, "paid_at", None) if doc else None
        status = _deadline_status(today=today, due_date=due_date, paid_at=paid_at)

        if paid_at:
            note = "Pago"
        elif status == "danger":
            note = "Atrasado"
        elif status == "warning":
            note = "Vence em breve"
        else:
            note = "No prazo"

        out.append(
            {
                "title": item["title"],
                "due_date": due_date,
                "paid_at": paid_at,
                "status": status,
                "note": note,
                "source": item["source"],
            }
        )

    if int(month) == 11:
        due_13_first = date(int(year), 11, 30)
        status_13_first = _deadline_status(today=today, due_date=due_13_first, paid_at=None)
        out.append(
            {
                "title": "13º salário - 1ª parcela",
                "due_date": due_13_first,
                "paid_at": None,
                "status": status_13_first,
                "note": "Conferir se todos os funcionários elegíveis receberam a 1ª parcela.",
                "source": "Regra CLT: até 30/11.",
            }
        )

    if int(month) == 12:
        due_13_second = date(int(year), 12, 20)
        status_13_second = _deadline_status(today=today, due_date=due_13_second, paid_at=None)
        out.append(
            {
                "title": "13º salário - 2ª parcela",
                "due_date": due_13_second,
                "paid_at": None,
                "status": status_13_second,
                "note": "Conferir se todos os funcionários elegíveis receberam a 2ª parcela.",
                "source": "Regra CLT: até 20/12.",
            }
        )

    return out


def _pending_center_sla(bucket: str) -> str:
    if bucket == "blocked":
        return "Resolver antes de fechar a competencia"
    if bucket == "overdue":
        return "SLA estourado - tratar hoje"
    if bucket == "today":
        return "SLA hoje (D-0)"
    if bucket == "next_7_days":
        return "Planejar e resolver nesta semana"
    return "Monitorar"


def _build_pending_center(checklist: dict[str, dict], obligations_agenda: list[dict]) -> list[dict]:
    out: list[dict] = []

    for key, item in checklist.items():
        if bool(item.get("ok")):
            continue
        out.append(
            {
                "source": "checklist",
                "key": key,
                "title": item.get("title") or "Pendencia de checklist",
                "description": item.get("help") or "",
                "bucket": "blocked",
                "sla": _pending_center_sla("blocked"),
                "action_url": item.get("action_url"),
                "action_label": item.get("action_label") or "Resolver",
                "due_date": None,
                "priority": 0,
            }
        )

    for item in obligations_agenda:
        bucket = item.get("bucket")
        if bucket not in ("overdue", "today", "next_7_days"):
            continue
        priority = {"overdue": 1, "today": 2, "next_7_days": 3}.get(bucket, 4)
        out.append(
            {
                "source": "agenda",
                "key": item.get("title") or "agenda",
                "title": item.get("title") or "Obrigacao",
                "description": item.get("why") or "",
                "bucket": bucket,
                "sla": _pending_center_sla(bucket),
                "action_url": item.get("action_url"),
                "action_label": item.get("action_label") or "Abrir",
                "due_date": item.get("due_date"),
                "priority": priority,
            }
        )

    out.sort(key=lambda row: (int(row.get("priority") or 99), row.get("due_date") is None, row.get("due_date") or date.max))
    return out


def _compute_competence_risk(checklist: dict[str, dict], pending_center: list[dict]) -> dict:
    checklist_blocked = sum(1 for item in checklist.values() if not bool(item.get("ok")))
    overdue_count = sum(1 for item in pending_center if item.get("bucket") == "overdue")
    today_count = sum(1 for item in pending_center if item.get("bucket") == "today")
    next_7_count = sum(1 for item in pending_center if item.get("bucket") == "next_7_days")

    score = min(100, (checklist_blocked * 20) + (overdue_count * 25) + (today_count * 15) + (next_7_count * 7))
    if score >= 70:
        level = "red"
        level_label = "Risco alto"
    elif score >= 35:
        level = "yellow"
        level_label = "Risco moderado"
    else:
        level = "green"
        level_label = "Risco controlado"

    reasons: list[str] = []
    if checklist_blocked:
        reasons.append(f"{checklist_blocked} pendencia(s) bloqueadora(s) no checklist")
    if overdue_count:
        reasons.append(f"{overdue_count} obrigacao(oes) em atraso")
    if today_count:
        reasons.append(f"{today_count} obrigacao(oes) vencendo hoje")
    if next_7_count:
        reasons.append(f"{next_7_count} obrigacao(oes) para os proximos 7 dias")
    if not reasons:
        reasons.append("Sem pendencias criticas no momento")

    return {
        "score": int(score),
        "level": level,
        "level_label": level_label,
        "checklist_blocked": checklist_blocked,
        "overdue_count": overdue_count,
        "today_count": today_count,
        "next_7_days_count": next_7_count,
        "reasons": reasons,
    }


def _official_guides_catalog(year: int, month: int) -> list[dict]:
    comp_label = f"{int(month):02d}/{int(year)}"
    return [
        {
            "dtype": "darf",
            "label": "DARF (Receita Federal)",
            "portal_label": "Portal e-CAC / Receita Federal",
            "portal_url": "https://www.gov.br/receitafederal/pt-br",
            "steps": [
                f"Acesse o portal oficial e abra a competência {comp_label}.",
                "Emita ou confira a DARF da folha e valide valor/vencimento.",
                "Anexe o PDF nesta tela e registre data de pagamento.",
            ],
        },
        {
            "dtype": "das",
            "label": "DAS (Simples Nacional)",
            "portal_label": "Portal do Simples Nacional",
            "portal_url": "https://www.gov.br/receitafederal/pt-br/assuntos/mei-simei/simei-simples-nacional",
            "steps": [
                f"Acesse o portal oficial e abra a competência {comp_label}.",
                "Gere a DAS e confira o vencimento e o valor apurado.",
                "Anexe o PDF nesta tela e registre data de pagamento.",
            ],
        },
        {
            "dtype": "fgts",
            "label": "FGTS Digital (GFD)",
            "portal_label": "Portal FGTS Digital",
            "portal_url": "https://www.gov.br/trabalho-e-emprego/pt-br/servicos/empregador/fgts-digital",
            "steps": [
                f"Acesse o portal oficial e abra a competência {comp_label}.",
                "Emita a guia FGTS Digital e confira vencimento e total.",
                "Anexe o PDF nesta tela e registre data de pagamento.",
            ],
        },
    ]


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


def _agenda_resolution_steps(bucket: str, action_label: str, title: str) -> list[str]:
    if bucket not in ("overdue", "today"):
        return []
    return [
        f"1) Clique em '{action_label}' e abra o item: {title}.",
        "2) Atualize os dados e confirme vencimento/pagamento para remover o alerta.",
        "3) Rode o compliance-check para validar se a pendência foi resolvida.",
    ]


def _build_obligations_agenda(year: int, month: int, docs: dict[str, GuideDocument | None]) -> list[dict]:
    today = date.today()
    ny, nm = _next_month(year, month)
    default_due = date(int(ny), int(nm), 20)

    agenda_items: list[dict] = []
    for key, title in (
        ("das", "Emitir e conferir DAS"),
        ("fgts", "Emitir e conferir FGTS Digital"),
        ("darf", "Emitir e conferir DARF da folha"),
    ):
        doc = docs.get(key)
        due_date = (getattr(doc, "due_date", None) if doc else None) or default_due
        paid_at = getattr(doc, "paid_at", None) if doc else None
        days_left = (due_date - today).days if due_date else None
        bucket = _agenda_bucket(days_left=days_left, paid_at=paid_at)
        action_label = "Abrir guias"
        title_full = title
        agenda_items.append(
            {
                "title": title_full,
                "due_date": due_date,
                "paid_at": paid_at,
                "days_left": days_left,
                "reminder": _reminder_label(days_left=days_left, paid_at=paid_at),
                "bucket": bucket,
                "action_url": url_for("payroll.close_home", year=year, month=month),
                "action_label": action_label,
                "why": "Evita atraso de encargos e reduz risco de multa/juros.",
                "resolution_steps": _agenda_resolution_steps(bucket=bucket, action_label=action_label, title=title_full),
            }
        )

    if int(month) == 11:
        due_13_first = date(int(year), 11, 30)
        days_left = (due_13_first - today).days
        bucket = _agenda_bucket(days_left=days_left, paid_at=None)
        action_label = "Ver funcionarios"
        title_full = "Conferir pagamento da 1a parcela do 13o"
        agenda_items.append(
            {
                "title": title_full,
                "due_date": due_13_first,
                "paid_at": None,
                "days_left": days_left,
                "reminder": _reminder_label(days_left=days_left, paid_at=None),
                "bucket": bucket,
                "action_url": url_for("payroll.employees"),
                "action_label": action_label,
                "why": "Ajuda a cumprir o prazo legal do 13o e evitar passivo trabalhista.",
                "resolution_steps": _agenda_resolution_steps(bucket=bucket, action_label=action_label, title=title_full),
            }
        )
    if int(month) == 12:
        due_13_second = date(int(year), 12, 20)
        days_left = (due_13_second - today).days
        bucket = _agenda_bucket(days_left=days_left, paid_at=None)
        action_label = "Ver funcionarios"
        title_full = "Conferir pagamento da 2a parcela do 13o"
        agenda_items.append(
            {
                "title": title_full,
                "due_date": due_13_second,
                "paid_at": None,
                "days_left": days_left,
                "reminder": _reminder_label(days_left=days_left, paid_at=None),
                "bucket": bucket,
                "action_url": url_for("payroll.employees"),
                "action_label": action_label,
                "why": "Ajuda a cumprir o prazo legal do 13o e evitar passivo trabalhista.",
                "resolution_steps": _agenda_resolution_steps(bucket=bucket, action_label=action_label, title=title_full),
            }
        )

    compliance_due = default_due - timedelta(days=2)
    compliance_days_left = (compliance_due - today).days
    compliance_bucket = _agenda_bucket(days_left=compliance_days_left, paid_at=None)
    compliance_action = "Abrir fechamento"
    compliance_title = "Rodar compliance-check final da competencia"
    agenda_items.append(
        {
            "title": compliance_title,
            "due_date": compliance_due,
            "paid_at": None,
            "days_left": compliance_days_left,
            "reminder": _reminder_label(days_left=compliance_days_left, paid_at=None),
            "bucket": compliance_bucket,
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": compliance_action,
            "why": "Detecta pendencias antes do vencimento das guias e evita retrabalho.",
            "resolution_steps": _agenda_resolution_steps(bucket=compliance_bucket, action_label=compliance_action, title=compliance_title),
        }
    )

    agenda_items.sort(key=lambda x: (x.get("due_date") is None, x.get("due_date") or date.max))
    return agenda_items


def _recommended_close_action(checklist: dict[str, dict]) -> dict | None:
    priority = ["revenue", "payroll", "taxes", "guides", "vacations", "thirteenth", "terminations", "leaves"]
    for key in priority:
        item = checklist.get(key)
        if item and not bool(item.get("ok")):
            return {
                "key": key,
                "title": item.get("title"),
                "help": item.get("help"),
                "action_url": item.get("action_url"),
                "action_label": item.get("action_label"),
            }
    return None


def _critical_close_pending_items(checklist: dict[str, dict]) -> list[dict]:
    critical_keys = ["revenue", "payroll", "taxes", "guides"]
    out: list[dict] = []
    for key in critical_keys:
        item = checklist.get(key)
        if item and not bool(item.get("ok")):
            out.append(
                {
                    "key": key,
                    "title": item.get("title"),
                    "help": item.get("help"),
                    "action_url": item.get("action_url"),
                    "action_label": item.get("action_label"),
                }
            )
    return out


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
    guides_catalog = _official_guides_catalog(year=year, month=month)
    guides_catalog_map = {row["dtype"]: row for row in guides_catalog}
    legal_deadlines = _build_legal_deadlines(year=year, month=month, docs=docs)
    obligations_agenda = _build_obligations_agenda(year=year, month=month, docs=docs)
    agenda_overdue = [item for item in obligations_agenda if item.get("bucket") == "overdue"]
    agenda_today = [item for item in obligations_agenda if item.get("bucket") == "today"]
    agenda_next_7_days = [item for item in obligations_agenda if item.get("bucket") == "next_7_days"]
    compliance_session_key = f"payroll_close_compliance:{year}-{month}"
    compliance_result = session.pop(compliance_session_key, None)

    summary = _calc_month_summary(run)
    revenue_summary = _calc_revenue_month_summary(year, month)
    vacations_summary = _calc_vacations_month_summary(year, month)
    thirteenth_summary = _calc_thirteenth_month_summary(year, month)
    terminations_summary = _calc_terminations_month_summary(year, month)
    leaves_summary = _calc_leaves_month_summary(year, month)

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
            "ok": all(bool(docs.get(k)) and bool(getattr(docs.get(k), "filename", None)) for k in ("darf", "das", "fgts")),
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
        "thirteenth": {
            "ok": True,
            "title": "13º no mês",
            "help": "Registre parcelas do 13º (1ª até 30/nov, 2ª até 20/dez) para controle.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(thirteenth_summary.get("count") or 0),
                "total_gross": thirteenth_summary.get("total_gross"),
            },
        },
        "terminations": {
            "ok": True,
            "title": "Rescisões no mês",
            "help": "Registre desligamentos para manter histórico trabalhista e controle de custos.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(terminations_summary.get("count") or 0),
                "total_gross": terminations_summary.get("total_gross"),
            },
        },
        "leaves": {
            "ok": True,
            "title": "Afastamentos no mês",
            "help": "Registre atestados/licenças para checagem de regras e histórico por funcionário.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(leaves_summary.get("count") or 0),
            },
        },
    }

    recommended_action = _recommended_close_action(checklist)
    critical_pending_items = _critical_close_pending_items(checklist)
    pending_center = _build_pending_center(checklist=checklist, obligations_agenda=obligations_agenda)
    competence_risk = _compute_competence_risk(checklist=checklist, pending_center=pending_center)
    evidence_events = (
        ComplianceEvidenceEvent.query.filter_by(year=year, month=month)
        .order_by(ComplianceEvidenceEvent.created_at.desc())
        .limit(30)
        .all()
    )

    return render_template(
        "payroll/close_home.html",
        year=year,
        month=month,
        docs=docs,
        guides_catalog_map=guides_catalog_map,
        run=run,
        closed=closed,
        checklist=checklist,
        recommended_action=recommended_action,
        critical_pending_items=critical_pending_items,
        pending_center=pending_center,
        competence_risk=competence_risk,
        evidence_events=evidence_events,
        summary=summary,
        legal_deadlines=legal_deadlines,
        obligations_agenda=obligations_agenda,
        agenda_overdue=agenda_overdue,
        agenda_today=agenda_today,
        agenda_next_7_days=agenda_next_7_days,
        compliance_result=compliance_result,
        revenue_summary=revenue_summary,
        vacations_summary=vacations_summary,
        thirteenth_summary=thirteenth_summary,
        terminations_summary=terminations_summary,
        leaves_summary=leaves_summary,
    )


@payroll_bp.post("/close/compliance")
@login_required
def close_run_compliance():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    apply_sync = (request.form.get("apply_sync") or "0") == "1"

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida para compliance-check.", "warning")
        return redirect(url_for("payroll.close_home"))

    try:
        result = run_compliance_check(target_year=year, apply_tax_sync=apply_sync)
        if result.get("ok"):
            flash("Compliance-check concluído sem alertas.", "success")
        else:
            flash(f"Compliance-check encontrou {len(result.get('issues') or [])} alerta(s).", "warning")

        payload = {
            "target_year": year,
            "target_month": month,
            "ok": bool(result.get("ok")),
            "issues_count": len(result.get("issues") or []),
            "report_lines": list(result.get("report_lines") or []),
            "sync_report_lines": list(result.get("sync_report_lines") or []),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
        session[f"payroll_close_compliance:{year}-{month}"] = payload
        session["payroll_last_compliance_check"] = {
            "target_year": payload["target_year"],
            "target_month": payload["target_month"],
            "ok": payload["ok"],
            "issues_count": payload["issues_count"],
            "ran_at": payload["ran_at"],
        }
        _add_evidence_event(
            year=year,
            month=month,
            event_type="compliance_check",
            details=f"ok={payload['ok']} issues={payload['issues_count']} apply_sync={int(apply_sync)}",
        )
        db.session.commit()
    except Exception as e:
        flash(f"Falha ao executar compliance-check: {e}", "warning")
        payload = {
            "target_year": year,
            "target_month": month,
            "ok": False,
            "issues_count": 1,
            "report_lines": [f"ERRO: {e}"],
            "sync_report_lines": [],
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
        session[f"payroll_close_compliance:{year}-{month}"] = payload
        session["payroll_last_compliance_check"] = {
            "target_year": payload["target_year"],
            "target_month": payload["target_month"],
            "ok": payload["ok"],
            "issues_count": payload["issues_count"],
            "ran_at": payload["ran_at"],
        }
        _add_evidence_event(
            year=year,
            month=month,
            event_type="compliance_check_error",
            details=f"erro={e}",
        )
        db.session.commit()

    return redirect(url_for("payroll.close_home", year=year, month=month))


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

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    comp = date(int(year), int(month), 1)
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)
    docs = {
        "darf": GuideDocument.query.filter_by(year=year, month=month, doc_type="darf").first(),
        "das": GuideDocument.query.filter_by(year=year, month=month, doc_type="das").first(),
        "fgts": GuideDocument.query.filter_by(year=year, month=month, doc_type="fgts").first(),
    }
    revenue_summary = _calc_revenue_month_summary(year, month)

    close_checklist = {
        "revenue": {
            "ok": bool(revenue_summary.get("count")),
            "title": "Receitas / notas do mês",
            "help": "Registre as notas (receitas) da competência.",
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
            "action_label": "Registrar receitas",
        },
        "payroll": {
            "ok": bool(run),
            "title": "Folha do mês",
            "help": "Crie/abra a folha da competência para gerar holerites.",
            "action_url": url_for("payroll.payroll_home", year=year, month=month),
            "action_label": "Abrir folha",
        },
        "taxes": {
            "ok": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
            "title": "Tabelas de INSS/IRRF",
            "help": "Sincronize ou configure as tabelas fiscais vigentes.",
            "action_url": url_for("payroll.tax_config"),
            "action_label": "Ver configurações",
            "meta": {"inss_eff": inss_eff, "irrf_eff": irrf_eff},
        },
        "guides": {
            "ok": all(bool(docs.get(k)) and bool(getattr(docs.get(k), "filename", None)) for k in ("darf", "das", "fgts")),
            "title": "Guias anexadas (DARF/DAS/FGTS)",
            "help": "Anexe os PDFs das guias da competência.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Anexar guias",
        },
    }

    critical_pending = _critical_close_pending_items(close_checklist)
    if critical_pending:
        flash("Não foi possível fechar: ainda existem pendências críticas na competência.", "warning")
        for item in critical_pending:
            flash(f"Pendente: {item['title']} — {item['help']}", "warning")
        return redirect(url_for("payroll.close_home", year=year, month=month))

    row = CompetenceClose.query.filter_by(year=year, month=month).first()
    if not row:
        row = CompetenceClose(year=year, month=month)
        db.session.add(row)
    _add_evidence_event(
        year=year,
        month=month,
        event_type="competence_marked_closed",
        details="Competência marcada como fechada",
    )
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
    _add_evidence_event(
        year=year,
        month=month,
        event_type="competence_reopened",
        details="Competência reaberta",
    )
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
    validation = _validate_guide_document(doc=doc, year=year, month=month, doc_type=doc_type)
    doc.validation_status = validation["status"]
    doc.validation_summary = validation["summary"]
    doc.validation_checked_at = datetime.utcnow()

    _add_evidence_event(
        year=year,
        month=month,
        event_type="guide_updated",
        entity_type="guide",
        entity_key=doc_type,
        details=f"status={validation['status']} summary={validation['summary']}",
    )

    db.session.commit()
    if validation["status"] == "danger":
        flash("Guia atualizada com alerta crítico de validação.", "warning")
    elif validation["status"] == "warning":
        flash("Guia atualizada com alerta de validação.", "warning")
    else:
        flash("Guia atualizada e validada.", "success")
    return redirect(url_for("payroll.close_home", year=year, month=month))
