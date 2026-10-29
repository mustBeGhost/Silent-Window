"""Readable, paginated research summaries; documents are generated in memory."""
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from xml.sax.saxutils import escape
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

FONT = 'SilentWindowVera'
pdfmetrics.registerFont(TTFont(FONT, str(Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf')))


def make_patient_pdf(detail, clinical, generated_at):
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = FONT
    styles.add(ParagraphStyle(name='SmallText',fontName=FONT,fontSize=8,leading=12,spaceAfter=5,wordWrap='CJK'))
    styles['BodyText'].fontSize=9;styles['BodyText'].leading=14
    glyphs = pdfmetrics.getFont(FONT).face.charToGlyph
    def text(value):
        return ''.join(c if glyphs.get(ord(c),0)>0 or c in '\n\t' else f'[U+{ord(c):04X}]' for c in str(value))
    def p(value, style='BodyText'):
        return Paragraph(escape(text(value)).replace('\n','<br/>'), styles[style])
    rows=[]
    def section(title): rows.extend([Spacer(1,10),p(title,'Heading2')])
    patient = detail['patient_id']; minute = clinical['as_of_minutes']
    rows += [p('Silent Window | Patient research summary','Title'),p(f'{patient} | Recorded view through {minute//60:02d}:{minute%60:02d} after admission'),p('RESEARCH DEMONSTRATION - NOT A CLINICAL CARE DOCUMENT','Heading3'),p('Recorded public ICU observations and staff-entered demonstration notes. No live hospital feed. Model scores are not verified probabilities of death. Staff additions are not model inputs. Unsupported font characters are written as U+ codes so their identity is retained.','SmallText'),p('Generated '+datetime.fromtimestamp(generated_at,timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),'SmallText')]
    section('Model assessments')
    rows.append(p('Model profile: '+clinical['model_profile']+'. Primary checkpoint: 12h. Checkpoints describe observation cutoffs, not prediction horizons.'))
    for point in detail['risk_trajectory']:
        score=point.get('risk_probability')
        rows.append(p(f"{point['checkpoint']}: "+(f"score {score:.4f}; category {point['risk_level']}; alert {point['alert_state']}" if score is not None else point['assessment_status'])))
    section('Admission and responsible doctor')
    context=clinical.get('context') or {}
    for key,label in [('diagnosis','Admission diagnosis'),('admission_reason','Reason for ICU admission'),('condition_summary','Condition summary'),('admission_severity','Admission severity'),('specialty','Specialty'),('physician_name','Responsible doctor')]:
        rows.append(p(label+': '+str(context.get(key) or 'Not provided')))
    if context.get('physician_id') and not context.get('physician_available'):
        rows.append(p('Responsible doctor is no longer an active assigned doctor; review the assignment.'))
    team=', '.join(person['display_name']+' ('+person['role']+')'+(' [inactive]' if not person['active'] else '') for person in clinical['assignments'])
    rows.append(p('Assigned team: '+(team or 'No staff assigned')))
    section('Latest recorded vital signs')
    table=[[p('Measurement','SmallText'),p('Value','SmallText'),p('Recorded minute / age','SmallText')]]
    for series in clinical['vitals']:
        latest=series['measurements'][-1] if series['measurements'] else None
        names={'SysABP':'Systolic BP (invasive, mmHg)','DiasABP':'Diastolic BP (invasive, mmHg)','MAP':'MAP (invasive, mmHg)','NISysABP':'Systolic BP (cuff, mmHg)','NIDiasABP':'Diastolic BP (cuff, mmHg)','NIMAP':'MAP (cuff, mmHg)','HR':'Heart rate (bpm)','RespRate':'Respiratory rate (breaths/min)','SaO2':'Arterial oxygen saturation (%)','Temp':'Temperature (C)','GCS':'Glasgow Coma Scale (/15)','Creatinine':'Creatinine (mg/dL)'}
        table.append([p(names.get(series['parameter'],series['parameter']),'SmallText'),p(latest['value'] if latest else 'Missing','SmallText'),p(f"{latest['time_minutes']} / {minute-latest['time_minutes']} minutes old" if latest else 'No observation supplied','SmallText')])
    t=Table(table,colWidths=[175,90,235],repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e5edf5')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#c4ccd6')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7)]));rows.append(t)
    section('Vital warnings and model acknowledgements')
    for warning in clinical['vital_warnings']:
        rows.append(p(f"{warning['parameter']}: {warning['state']}; entered limits {warning['lower']} to {warning['upper']}"))
    if not clinical['rules']: rows.append(p('No doctor-entered vital limits configured. This does not mean readings are normal.'))
    for ack in clinical['acknowledgements']:
        rows.append(p(f"{ack['checkpoint']}: acknowledged by {ack['author']} - {ack['content']}"))
    rows.append(p('Acknowledging or resolving a staff request does not clear a model alert or confirm treatment.'))
    section('Follow-ups')
    counts=clinical['follow_ups']['counts'];rows.append(p(f"Pending {counts['pending']}; completed {counts['completed']}; overdue at recorded cutoff {counts['overdue']}."))
    for item in clinical['follow_ups']['items'][:30]:
        rows.append(p(f"#{item['entry_id']} [{item['status']}] {item['follow_up'] or item['assessment']} | Next review minute: {item['review_minute']}"))
    section('Doctor review requests')
    for item in clinical['review_requests']['items'][:30]:
        rows.append(p(f"#{item['request_id']} [{item['status']}] {item['reason']} | Requested by {item['author']} at minute {item['minute']}"))
        if item['status_note']: rows.append(p(f"{item['status_author']}: {item['status_note']}"))
    if not clinical['review_requests']['items']:rows.append(p('No requests in this recorded view.'))
    section('Recent staff demonstration notes')
    for entry in clinical['entries'][:30]:
        saved=datetime.fromtimestamp(entry['created_at'],timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        rows.append(p(f"{entry['kind']} | {entry['author']} | recorded minute {entry['minute']} | saved {saved}",'Heading3'))
        for key in ('assessment','plan','follow_up','escalation'):
            if entry[key]: rows.append(p(key.replace('_',' ').capitalize()+': '+entry[key]))
    rows.append(p('This summary includes up to 30 items per follow-up, review-request and clinical-note section. Counts may include more items. Use staff history search for older records. Data may change after export.','SmallText'))
    def footer(canvas, doc):
        canvas.saveState();canvas.setFont(FONT,8);canvas.drawString(42,24,patient+' | Research demonstration');canvas.drawRightString(A4[0]-42,24,'Page '+str(doc.page));canvas.restoreState()
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=40,bottomMargin=42,title='Silent Window research summary',author='Silent Window')
    doc.build(rows,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
