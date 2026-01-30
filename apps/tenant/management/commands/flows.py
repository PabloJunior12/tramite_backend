from django.core.management.base import BaseCommand
from django.db import connections
from apps.tramite.models import Procedure, ProcedureFlow, Area
from apps.user.models import User
from django.utils.timezone import make_aware
from apps.tenant.utils import parse_origin_options

STATUS_MAP = {
    "Enviado": ProcedureFlow.SENT,
    "Recepcionado": ProcedureFlow.RECEIVED,
    "Finalizado": ProcedureFlow.FINALIZED,
    "Por finalizar": ProcedureFlow.SENT,
    "Observado": ProcedureFlow.OBSERVED,
    "Rechazado": ProcedureFlow.REJECTED,
}

FINAL_STATES = {"Finalizado"}

class Command(BaseCommand):
    help = "Migrar historial de trámites (ProcedureFlow)"

    def handle(self, *args, **options):
        with connections['legacy'].cursor() as cursor:
            cursor.execute("""
                SELECT
                    h.*,
                    t.codigo AS tramite_codigo,
                    t.agency_id AS tramite_agency_id,
                    ao.initials AS origen_initials,
                    ad.initials AS destino_initials,
                    u.username AS username
                FROM historicos h
                INNER JOIN tramites t ON t.id = h.tramite_id
                LEFT JOIN areas ao ON ao.id = h.origen_id
                LEFT JOIN areas ad ON ad.id = h.destino_id
                LEFT JOIN users u ON u.id = h.user_id
                WHERE h.solo_visualizacion = 0
                ORDER BY h.tramite_id, h.secuencia
              
            """)

            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            total = len(rows)
            print(total)
        for row in rows:

            data = dict(zip(columns, row))
       
            try:
                procedure = Procedure.objects.get(
                    code=data["codigo"],
                    agency_id=data["tramite_agency_id"]
                )
            except Procedure.DoesNotExist:
                continue

            print(data['tramite_agency_id'], data["codigo"], procedure.agency.pk, procedure.code)

            from_area = Area.objects.filter(
                initials__iexact=data["origen_initials"]
            ).first()

            to_area = Area.objects.filter(
                initials__iexact=data["destino_initials"]
            ).first()

            user = User.objects.filter(
                username=data["username"]
            ).first()

            # Área por defecto (solo una vez fuera del loop si quieres optimizar)
            first_area = Area.objects.order_by("id").first()

            # 🔁 Regla especial para TV
            if data["tipo_tramite"] == "TV" and data["secuencia"] <= 2:
                  
                  from_area_final = first_area

            else:
                  
                  from_area_final = from_area

            if not to_area or not user:

                continue

            origen_asunto = data.get("origen_asunto")
            procedure_subject = procedure.subject

            subject_derivar = None

            if origen_asunto and origen_asunto.strip() != procedure_subject.strip():
                subject_derivar = origen_asunto
            
            is_derive = (
                data["secuencia"] > 3
                or (
                    data["secuencia"] == 3
                    and data["estado_tramite"] not in FINAL_STATES
                )
            )

            origin_options = parse_origin_options(data.get("destino_asunto"))

            if data["estado_tramite"] == "Observado":
               
               comment = data.get("observacion")

            else:
               
               comment = data.get("comentario")

            procedure = ProcedureFlow.objects.create(
                procedure=procedure,
                from_area=from_area_final,
                to_area=to_area,
                flow_type=ProcedureFlow.NORMAL,
                status=STATUS_MAP.get(
                    data["estado_tramite"],
                    ProcedureFlow.SENT
                ),
                subject=procedure.subject,
                subject_derivar=subject_derivar,
                comment=comment,
                sent_by=user,
                sequence=data["secuencia"],
                # sent_at=make_aware(data["created_at"])
                # if data.get("created_at") else None,

                origin_options=origin_options,
                is_active=(
                        data["estado"] == "V"
                        or data["estado_tramite"] == "Observado"
                ),
                is_to_finalize = data["estado_tramite"] == "Por finalizar" or data["operacion"] == "PF",
                is_derive = is_derive
            )

            procedure.created_at = make_aware(data["created_at"])
            procedure.save(update_fields=["created_at"])