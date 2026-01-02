from django.db import transaction
from django.utils import timezone
from django.utils.timezone import localtime
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

from .models import Agency, ProcedureSequence, ProcedureFlow, Area, WorkSchedule, Holiday, Procedure
from datetime import datetime, time
import qrcode
import base64
import os
import random
from io import BytesIO

def generate_procedure_code(agency: Agency) -> str:
    year = timezone.now().year

    with transaction.atomic():
        sequence, _ = ProcedureSequence.objects.select_for_update().get_or_create(
            agency=agency,
            year=year
        )

        sequence.last_number += 1
        sequence.save()

        number_formatted = str(sequence.last_number).zfill(6)
        return f"{number_formatted}-{year}"

def get_next_sequence(procedure):
    last = (
        ProcedureFlow.objects
        .filter(
            procedure=procedure,
            flow_type=ProcedureFlow.NORMAL,
            )
        .order_by("-sequence")
        .first()
    )
    return 1 if not last else last.sequence + 1

def generar_qr_base64(url: str) -> str:

    qr = qrcode.make(url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_base64}"

def get_virtual_areas():

    tramite_virtual = Area.objects.get(
        agency__name="Andahuaylas",
        type="TV"
    )

    mesa_partes = Area.objects.get(
        agency__name="Andahuaylas",
        code="001"
    )

    return tramite_virtual, mesa_partes

class ScheduleResult:
    IN_SCHEDULE = "IN_SCHEDULE"
    OUT_OF_SCHEDULE = "OUT_OF_SCHEDULE"
    NO_LABORABLE = "NO_LABORABLE"

def check_schedule(now=None):
    """
    Valida si una fecha/hora está dentro del horario laboral
    """
    now = localtime(now)
    today = now.date()
    weekday = now.weekday()  # 0=lunes, 6=domingo
    current_time = now.time()

    # ❌ Domingo
    if weekday == 6:
        return ScheduleResult.NO_LABORABLE

    # ❌ Feriado
    if Holiday.objects.filter(date=today, is_active=True).exists():
        return ScheduleResult.NO_LABORABLE

    # ⏱️ Buscar horario
    schedule = WorkSchedule.objects.filter(
        day=weekday,
        is_active=True
    ).first()

    if not schedule:
        return ScheduleResult.OUT_OF_SCHEDULE

    if schedule.start_time <= current_time <= schedule.end_time:
        return ScheduleResult.IN_SCHEDULE

    return ScheduleResult.OUT_OF_SCHEDULE

def send_procedure_email(procedure, is_out_of_schedule=False):
    """
    Envía constancia de registro de trámite virtual
    """

    if not procedure.sender_email:
        return

    subject = "Constancia de Registro – Mesa de Partes Virtual"

    html_content = build_procedure_email_html(
        procedure=procedure,
        is_out_of_schedule=is_out_of_schedule
    )

    text_content = (
        f"Su trámite fue registrado correctamente.\n"
        f"Código de seguimiento: {procedure.tracking_code}\n"
        f"Mesa de Partes Virtual – ADEA"
    )

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[procedure.sender_email],
    )

    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)

def build_procedure_email_html(procedure, is_out_of_schedule):
    status_block = ""
    if is_out_of_schedule:
        status_block = f"""
        <div style="background:#fff3cd; padding:12px; border-radius:4px; margin-bottom:15px;">
            <strong>⚠ Atención:</strong><br>
            Su trámite fue registrado <b>fuera del horario laboral</b> y será
            procesado automáticamente el <b>siguiente día hábil</b>.
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Constancia de Registro</title>
    </head>
    <body style="margin:0; padding:0; background-color:#f4f6f8; font-family:Arial, Helvetica, sans-serif;">
        <div style="max-width:600px; margin:30px auto; background:#ffffff; padding:25px; border-radius:6px;">

            <h2 style="color:#0d6efd; margin-top:0;">
                Mesa de Partes Virtual
            </h2>

            <p>Estimado(a) <strong>{procedure.sender_name}</strong>,</p>

            {status_block}

            <p>
                Su trámite ha sido <strong>registrado correctamente</strong>
                en la Mesa de Partes Virtual de la institución.
            </p>

            <div style="background:#f8f9fa; padding:15px; border-radius:4px; margin:20px 0;">
                <p style="margin:0; font-size:14px; color:#6c757d;">
                    Código de seguimiento
                </p>
                <p style="margin:5px 0 0; font-size:22px; font-weight:bold; color:#000;">
                    {procedure.tracking_code}
                </p>
            </div>

            <p>
                Con este código podrá realizar el seguimiento de su trámite
                a través del portal institucional.
            </p>

            <p style="margin-top:25px;">
                Atentamente,<br>
                <strong>Mesa de Partes Virtual</strong><br>
                <span style="color:#6c757d;">ADEA</span>
            </p>

            <hr style="border:none; border-top:1px solid #e9ecef; margin:25px 0;">

            <p style="font-size:12px; color:#6c757d;">
                Este correo ha sido generado automáticamente.
                Por favor no responda a este mensaje.
            </p>

        </div>
    </body>
    </html>
    """

def get_flow_status_display(flow):
    """
    Replica exactamente la lógica de estados del frontend (Angular)
    """

    # 🛑 PRIORIDAD 1: OBSERVED
    if flow.status == "OBSERVED":
        return {
            "label": "Observado",
            "class": "text-bg-warning"
        }

    # 🔥 PRIORIDAD 2: Por Finalizar
    if flow.is_to_finalize:
        return {
            "label": "Finalizado",
            "class": "text-bg-dark"
        }

    # 🔁 Resto de estados
    if flow.status == "FINALIZED":
        return {"label": "Finalizado", "class": "text-bg-dark"}

    if flow.status == "SENT":
        return {"label": "Enviado", "class": "text-bg-primary"}

    if flow.status == "RECEIVED":
        return {"label": "Recepcionado", "class": "text-bg-info"}

    if flow.status == "REJECTED":
        return {"label": "Rechazado", "class": "text-bg-danger"}

    return {
        "label": flow.status or "—",
        "class": "text-bg-secondary"
    }

def get_flow_global_status_display(flow):

    # 🛑 PRIORIDAD 1: OBSERVED
    if flow.status == "OBSERVED":
        return {
            "label": "Observado",
            "class": "text-bg-warning"
        }

    # 🔥 PRIORIDAD 2: Por Finalizar
    if flow.is_to_finalize:
        return {
            "label": "Por finalizar",
            "class": "text-bg-dark"
        }

    # 🔁 Resto de estados
    if flow.status == "FINALIZED":
        return {"label": "Finalizado", "class": "text-bg-dark"}

    if flow.status == "SENT":
        return {"label": "Enviado", "class": "text-bg-primary"}

    if flow.status == "RECEIVED":
        return {"label": "Recepcionado", "class": "text-bg-info"}

    if flow.status == "REJECTED":
        return {"label": "Rechazado", "class": "text-bg-danger"}

    return {
        "label": flow.status or "—",
        "class": "text-bg-secondary"
    }

def generate_tracking_code():

    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(random.choices(chars, k=6))

def generate_unique_tracking_code():

    while True:
        code = generate_tracking_code()
        if not Procedure.objects.filter(tracking_code=code).exists():
            return code