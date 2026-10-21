"""Sales CRM 2.0, run 5b: Set-up > Automation > Rules (automation rules), Set-up > Pipelines & products > Scoring
(lead scoring), "AI on the lead page" (the switch on Automation's Overview and the lead page's Summarise) and "OK to
send offers" on the contact page.

Rules on crm_bp (both consoles). The set-up endpoints are in MANAGE (routes/crm.py) and admin_only; Summarise and
the offers switch are daily work (the lead / contact lookups check who may see what). The logic is in
services/crm_rules.py, crm_scoring.py, crm_ai.py and crm_consent.py.
"""
from flask import abort, flash, jsonify, redirect, render_template, request
from flask_login import current_user

from app import db
from app.models import ActivityEvent, CrmRule, CrmScoreRule, CrmSource
from app.routes.crm import _common, _lead_or_404, admin_only, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm_ai, crm_consent, crm_rules, crm_scoring, crm_scope


# ============================================================================================ Rules

def _rule_or_404(rule_id):
    rule = db.session.get(CrmRule, rule_id)
    if rule is None or not crm_scope.visible(rule):
        abort(404)
    return rule


def _rules_page(edit=None, values=None, errors=None, test=None, status=200):
    ch = crm_rules.choices()
    rules = CrmRule.query.order_by(CrmRule.position, CrmRule.id).all()
    clashes = {c['rule_id']: c['why'] for c in crm_rules.stage_conflicts([r for r in rules if r.active])}
    if values is None:
        values = crm_rules.form_values(edit if edit is not None and edit != 'new' else None)
    return render_template('cs/crm/rules.html', rules=rules, ch=ch, clashes=clashes, edit=edit, v=values,
                           errors=errors or [], test=test, R=crm_rules, describe=lambda r: crm_rules.describe(r, ch),
                           webhook_ready=bool(crm_rules.os.environ.get(crm_rules.WEBHOOK_ENV)),
                           **_common()), status


@crm_bp.route('/rules')
@cs_required
@admin_only
def rules():
    """Set-up > Automation > Rules: the list, and the When / If / Then editor (?edit=<id> or new)."""
    arg = request.args.get('edit')
    edit = 'new' if arg == 'new' else (_rule_or_404(int(arg)) if arg and arg.isdigit() else None)
    return _rules_page(edit=edit)


def _editing():
    rid = request.form.get('id')
    return _rule_or_404(int(rid)) if rid and rid.isdigit() else None


@crm_bp.route('/rules/save', methods=['POST'])
@cs_required
@admin_only
def rule_save():
    rule = _editing()
    data, errors = crm_rules.clean(request.form)
    if errors:
        return _rules_page(edit=rule or 'new', values=request.form.to_dict(), errors=errors, status=400)
    is_new = rule is None
    rule = crm_rules.save(rule, data, current_user)
    ActivityEvent.log('crm_rule_saved', actor=current_user, rule=rule.id, new=is_new)
    db.session.commit()
    flash('Saved “%s”.%s' % (rule.name, ' Switch it on when you are ready.' if not rule.active else ''), 'success')
    return redirect(crm_url('rules'))


@crm_bp.route('/rules/test', methods=['POST'])
@cs_required
@admin_only
def rule_test():
    """"Which open leads would this match now?": a count and five examples. Nothing is saved or run."""
    rule = _editing()
    data, errors = crm_rules.clean(request.form)
    # the test needs only the When and the If: a missing name or action is no reason not to show it
    shown = [e for e in errors if e not in ('Give the rule a name.', 'Add at least one thing to do.')]
    test = None if shown else crm_rules.preview(crm_rules.Draft(data), current_user)
    return _rules_page(edit=rule or 'new', values=request.form.to_dict(), errors=shown, test=test,
                       status=400 if shown else 200)


@crm_bp.route('/rules/<int:rule_id>/switch', methods=['POST'])
@cs_required
@admin_only
def rule_toggle(rule_id):
    rule = _rule_or_404(rule_id)
    rule.active = request.form.get('on') == '1'
    crm_rules.forget()
    ActivityEvent.log('crm_rule_switched', actor=current_user, rule=rule.id, on=rule.active)
    db.session.commit()
    flash('“%s” is %s.' % (rule.name, 'on' if rule.active else 'off'), 'success')
    return redirect(crm_url('rules'))


@crm_bp.route('/rules/<int:rule_id>/delete', methods=['POST'])
@cs_required
@admin_only
def rule_delete(rule_id):
    rule = _rule_or_404(rule_id)
    name = rule.name
    crm_rules.delete(rule)
    ActivityEvent.log('crm_rule_deleted', actor=current_user, rule=rule_id)
    db.session.commit()
    flash('Deleted “%s”.' % name, 'success')
    return redirect(crm_url('rules'))


# ============================================================================================ AI on the lead page

@crm_bp.route('/automatic/ai', methods=['POST'])
@cs_required
@admin_only
def ai_switch():
    """Automation > Overview, "AI on the lead page": on or off (the server's key decides whether it can work)."""
    on = request.form.get('on') == '1'
    crm_ai.switch(on, current_user)
    ActivityEvent.log('crm_ai_switched', actor=current_user, on=on)
    db.session.commit()
    if on and not crm_ai.has_key():
        flash('Switched on. It starts working once the server has its Anthropic key.', 'warning')
    else:
        flash('AI on the lead page is %s.' % ('on' if on else 'off'), 'success')
    return redirect(crm_url('automatic'))


@crm_bp.route('/lead/<int:lead_id>/ai', methods=['POST'])
@cs_required
def ai_summary(lead_id):
    """Summarise: 3-5 lines and a suggested next message (only for the message box; nothing is sent)."""
    lead = _lead_or_404(lead_id)
    if not crm_ai.enabled():
        return jsonify({'error': crm_ai.UNAVAILABLE}), 503
    try:
        got = crm_ai.summarise(lead, fresh=bool((request.get_json(silent=True) or {}).get('fresh')))
    except crm_ai.AIError:
        db.session.rollback()
        return jsonify({'error': crm_ai.UNAVAILABLE}), 503
    if not got.get('cached'):
        ActivityEvent.log('crm_ai_summary', actor=current_user, lead_id=lead.id)
    db.session.commit()
    return jsonify({'success': True, **got})


# ============================================================================================ Scoring

def _scoring_back():
    return redirect(crm_url('pipelines', tab='scoring'))


@crm_bp.route('/pipelines/scoring/switch', methods=['POST'])
@cs_required
@admin_only
def scoring_switch():
    """"Turn scoring on" / off. On: every open lead is scored now and its rating follows (unless a person picked
    it). Off: nothing changes any more; ratings stay as they are."""
    on = request.form.get('on') == '1'
    crm_scoring.ensure_starter()
    crm_scoring.save_state(on=on, actor=current_user)
    ActivityEvent.log('crm_scoring_switched', actor=current_user, on=on)
    db.session.commit()
    if on:
        n = crm_scoring.recalc_all()
        crm_scoring.save_state(day=None)
        flash('Scoring is on. %d lead%s changed.' % (n, '' if n == 1 else 's'), 'success')
    else:
        flash('Scoring is off. Ratings stay as they are.', 'success')
    return _scoring_back()


@crm_bp.route('/pipelines/scoring', methods=['POST'])
@cs_required
@admin_only
def scoring_save():
    """The thresholds: from which score a lead is Ready to buy, and Thinking about it."""
    try:
        hot, warm = crm_scoring.thresholds(request.form.get('hot'), request.form.get('warm'))
    except ValueError as exc:
        flash(str(exc), 'danger')
        return _scoring_back()
    crm_scoring.save_state(hot=hot, warm=warm, actor=current_user)
    if crm_scoring.is_on():
        crm_scoring.recalc_all()
    flash('Saved.', 'success')
    return _scoring_back()


@crm_bp.route('/pipelines/scoring/line', methods=['POST'])
@cs_required
@admin_only
def score_rule_save():
    rid = request.form.get('id')
    line = db.session.get(CrmScoreRule, int(rid)) if rid and rid.isdigit() else None
    if line is not None and not crm_scope.visible(line):
        abort(404)
    data, err = crm_scoring.clean_line(request.form)
    if err:
        flash(err, 'danger')
        return _scoring_back()
    if line is None:
        top = db.session.query(db.func.max(CrmScoreRule.position)).scalar() or 0
        line = CrmScoreRule(position=top + 1)
        db.session.add(line)
    for k, v in data.items():
        setattr(line, k, v)
    db.session.commit()
    if crm_scoring.is_on():
        crm_scoring.recalc_all()
    flash('Saved “%s”.' % line.name, 'success')
    return _scoring_back()


@crm_bp.route('/pipelines/scoring/line/<int:line_id>/delete', methods=['POST'])
@cs_required
@admin_only
def score_rule_delete(line_id):
    line = db.session.get(CrmScoreRule, line_id)
    if line is None or not crm_scope.visible(line):
        abort(404)
    db.session.delete(line)
    db.session.commit()
    if crm_scoring.is_on():
        crm_scoring.recalc_all()
    flash('Deleted.', 'success')
    return _scoring_back()


def scoring_context():
    """What the Scoring tab draws (routes/crm_setup.pipelines, ?tab=scoring)."""
    crm_scoring.ensure_starter()
    return {'score_state': crm_scoring.state(), 'score_lines': crm_scoring.lines(), 'SIGNALS': crm_scoring.SIGNALS,
            'DAY_SIGNALS': crm_scoring.DAY_SIGNALS, 'describe_line': crm_scoring.describe_line,
            'score_fields': list(crm_scoring.FIELD_CHOICES.items()) + [('details.' + k, l)
                                                                      for k, l in crm_rules.detail_fields()],
            'score_sources': CrmSource.query.order_by(CrmSource.name).all()}


# ============================================================================================ OK to send offers

@crm_bp.route('/contact/<int:person_id>/offers', methods=['POST'])
@cs_required
def contact_offers(person_id):
    """The contact page's "OK to send offers" switch: when and by whom is kept with it. Sends nothing."""
    from app.routes.crm_people import _person_or_404
    person = _person_or_404(person_id)
    on = request.form.get('on') == '1'
    if crm_consent.set_offers(person, on, crm_consent.HOW_PAGE, by=current_user):
        db.session.commit()
        flash('OK to send offers: %s.' % ('yes' if on else 'no'), 'success')
    return redirect(crm_url('contact', person_id=person.id))


@crm_bp.app_template_global('RET_TEXT')
def ret_text(ret):
    """'3.2×' for a campaign's return (Sales results > Campaigns)."""
    from app.services import crm_campaigns
    return crm_campaigns.ret_text(ret)


@crm_bp.app_template_global('OFFERS_LINE')
def offers_line(person):
    """'Given 21 Oct 2026 · ticked on the form “Diwali offer”' (the contact page)."""
    return crm_consent.line(person)
