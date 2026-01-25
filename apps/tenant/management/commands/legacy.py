from django.core.management.base import BaseCommand
from django.db import connections
from apps.tramite.models import Agency, Document, Procedure, Area
from apps.user.models import User
from django.utils.timezone import make_aware

class Command(BaseCommand):
    help = "Migrar procedimientos desde MySQL legacy"

    def handle(self, *args, **options):
        with connections['legacy'].cursor() as cursor:
            cursor.execute("""
                SELECT 
                    t.*,
                    ao.initials AS origen_initials,
                    ad.initials AS destino_initials,
                    u.username AS username
                FROM tramites t
                LEFT JOIN areas ao ON ao.id = t.origen_id
                LEFT JOIN areas ad ON ad.id = t.destino_id
                LEFT JOIN users u ON u.id = t.user_id
                
            """)

            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()

        data = [dict(zip(columns, row)) for row in rows]

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

           
                Procedure.objects.create(
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
                    created_by=user,
                    created_at=make_aware(item["created_at"]),
                    tracking_code=item["unique_id"] if item["tipo_tramite"] == "TV" else None,
                    code_destino=None,
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