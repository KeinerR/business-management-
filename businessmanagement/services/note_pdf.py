from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def debit_note_pdf(note):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()

    def text(value, style='BodyText'):
        return Paragraph(escape(str(value or '')).replace('\n', '<br/>'), styles[style])

    elements = [text(f'NOTA DE DÉBITO {note.debit_note_number}', 'Heading1')]
    details = [
        ('Empresa', note.business.business_name),
        ('Cliente', note.third_party.name if note.third_party else 'Sin tercero'),
        ('Factura asociada', note.invoice.invoice_number if note.invoice else 'Sin factura'),
        ('Fecha de emisión', note.issue_date.strftime('%d/%m/%Y')),
        ('Estado', note.get_status_display()), ('Moneda', note.currency),
    ]
    elements += [Table([[text(label), text(value)] for label, value in details],
                       colWidths=[45 * mm, 135 * mm]), Spacer(1, 6 * mm)]
    if note.description:
        elements += [text(note.description), Spacer(1, 4 * mm)]
    rows = [[text(label) for label in ['Descripción', 'Cantidad', 'Precio unitario', 'Subtotal']]]
    for item in note.items.all():
        rows.append([text(item.description), text(item.quantity), text(f'{item.unit_price:,.2f}'),
                     text(f'{item.subtotal:,.2f}')])
    table = Table(rows, colWidths=[90 * mm, 23 * mm, 34 * mm, 33 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8f3f0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), .5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    elements += [table, Spacer(1, 6 * mm)]
    # Stored totals preserve the issued document even if tax rules change later.
    totals = [('Subtotal', note.subtotal), ('Impuestos', note.tax_amount),
              ('Retenciones', -note.retention_amount), ('Total', note.total)]
    elements.append(Table([[text(label), text(f'{amount:,.2f} {note.currency}')]
                           for label, amount in totals], colWidths=[110 * mm, 70 * mm]))
    if note.notes:
        elements += [Spacer(1, 5 * mm), text('Observaciones', 'Heading3'), text(note.notes)]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f'Página {document.page}')
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    return buffer
