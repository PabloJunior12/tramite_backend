from django.core.management.base import BaseCommand
from django.db import connections
from apps.tramite.models import Agency, Document, Procedure, Area, ProcedureFile, ProcedureSequence
from apps.user.models import User
from django.utils.timezone import make_aware
import os
from django.core.files import File
from collections import defaultdict
from apps.tenant.utils import extract_sequence_and_year, resolve_location_from_procedencia

OLD_MEDIA_PATH = "media/img"

def migrate_procedure_files(procedure, filenames, user):
    if not filenames:
        return

    files = [f.strip() for f in filenames.split(",") if f.strip()]

    for filename in files:
        old_path = os.path.join(OLD_MEDIA_PATH, filename)

        if not os.path.exists(old_path):
            print(f" Archivo no encontrado: {old_path}")
            continue

        with open(old_path, "rb") as f:
            ProcedureFile.objects.create(
                procedure=procedure,
                uploaded_by=user,
                file=File(f, name=filename),
            )

class Command(BaseCommand):
    help = "Migrar procedimientos desde MySQL legacy"

    def handle(self, *args, **options):
        with connections['legacy'].cursor() as cursor:
            cursor.execute("""
                SELECT 
                    t.*,
                    ao.initials AS origen_initials,
                    ad.initials AS destino_initials,
                    ad.type_tramite AS destino_type, 
                    u.username AS username
                FROM tramites t
                LEFT JOIN areas ao ON ao.id = t.origen_id
                LEFT JOIN areas ad ON ad.id = t.destino_id
                LEFT JOIN users u ON u.id = t.user_id
            """)

            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        data = [dict(zip(columns, row)) for row in rows]

        max_sequence_by_agency_year = defaultdict(int)

        for item in data:
            try:
                
                agency = Agency.objects.get(id=item["agency_id"])
                document = Document.objects.get(id=item["documento_id"])
                user = User.objects.get(username=item["username"])

                from_area = Area.objects.filter(
                    initials__iexact=item["origen_initials"]
                ).first()

                to_area = Area.objects.filter(
                    initials__iexact=item["destino_initials"]
                ).first()

                # Área por defecto (solo una vez fuera del loop si quieres optimizar)
                first_area = Area.objects.order_by("id").first()

                # 🔁 Regla especial para TV
                if item["tipo_tramite"] == "TV":

                    from_area_final = first_area

                else:
                    
                    from_area_final = from_area

                department_id = item.get("department_id")
                province_id = item.get("province_id")
                district_id = item.get("district_id")

                if not department_id or not province_id or not district_id:
                    department, province, district = resolve_location_from_procedencia(
                        item.get("procedencia")
                    )

                    department_id = department.id if department else None
                    province_id = province.id if province else None
                    district_id = district.id if district else None

                is_annulled = item['status'] == 'anulado'

                procedure = Procedure.objects.create(
                    code=item["codigo"],
                    agency=agency,
                    document_type=document,
                    document_number=item["documento_nro"],
                    folios=item["folios_nro"] or 0,
                    sender_dni=item["dni"],
                    sender_name=item["razon_social"],
                    sender_representante=item["representante"],
                    sender_address=item["direccion"],
                    sender_phone=item["celular"],
                    sender_email=item["email"],
                    from_area=from_area_final,
                    to_area=to_area,
                    subject = item["asunto"] or "-",
                    is_virtual=item["tipo_tramite"] == "TV",
                    is_annulled = is_annulled,
                    created_by=user,
                    tracking_code=item["unique_id"] if item["tipo_tramite"] == "TV" else None,
                    code_destino=None,
                    department_id=department_id,
                    province_id=province_id,
                    district_id=district_id
                )

                procedure.created_at = make_aware(item["created_at"])
                procedure.save(update_fields=["created_at"])


                migrate_procedure_files(
                    procedure=procedure,
                    filenames=item.get("archivo"),
                    user=user
                )

                # 🔢 Calcular secuencia
                seq, year = extract_sequence_and_year(item["codigo"])
                if seq is not None and year is not None:
                    key = (agency.id, year)
                    if seq > max_sequence_by_agency_year[key]:
                        max_sequence_by_agency_year[key] = seq

                self.stdout.write(
                    self.style.SUCCESS(f"Migrado: {item['codigo']}")
                )

                self.stdout.write(
                    self.style.SUCCESS(f"Migrado: {item['codigo']}")
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error en {item['codigo']}: {str(e)}"
                    )
                )

        # Actualizar ProcedureSequence
        for (agency_id, year), last_seq in max_sequence_by_agency_year.items():
            ProcedureSequence.objects.update_or_create(
                agency_id=agency_id,
                year=year,
                defaults={"last_number": last_seq},
            )

        self.stdout.write(
            self.style.SUCCESS("✅ Migración finalizada correctamente")
        )