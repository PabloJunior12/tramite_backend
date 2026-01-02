from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid

User = settings.AUTH_USER_MODEL

class Department(models.Model):

    id = models.CharField(primary_key=True,max_length=2)
    description = models.CharField(max_length=255,)
    active = models.BooleanField(default=True)

class Province(models.Model):

    id = models.CharField(primary_key=True, max_length=4)
    description = models.CharField(max_length=255)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    active = models.BooleanField(default=True)

class District(models.Model):
    
    id = models.CharField(primary_key=True, max_length=6)
    description = models.CharField(max_length=255)
    province = models.ForeignKey(Province,on_delete=models.CASCADE)
    active = models.BooleanField(default=True, verbose_name='Activo')

class Company(models.Model):

    name = models.CharField(max_length=255, verbose_name="Nombre de la empresa")
    ruc = models.CharField(max_length=11, unique=True, verbose_name="RUC")
    address = models.CharField(max_length=255, verbose_name="Dirección", null=True, blank=True)
    phone = models.CharField(max_length=20, verbose_name="Teléfono", null=True, blank=True)
    email = models.EmailField(verbose_name="Correo electrónico", null=True, blank=True)
    logo = models.ImageField(upload_to="logos/", verbose_name="Logo", null=True, blank=True)

    def __str__(self):
        return self.name

class Document(models.Model):

    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=100)
 
    def __str__(self):
        return self.name

class Agency(models.Model):

    name = models.CharField(max_length=150)
    direccion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Area(models.Model):

    TYPE_CHOICES = [
        ("TE", "Tramite externo"),
        ("TI", "Tramite interno"),
        ("TV", "Tramite virtual"),
    ]

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=3, unique=True, editable=False)
    state = models.BooleanField(default=True)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default="TI")
    initials = models.CharField(max_length=50, null=True, blank=True)

    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name='areas',
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):

        if not self.code:

            last= Area.objects.order_by('-id').first()

            next_number = 1 if not last else int(last.code) + 1

            self.code = str(next_number).zfill(3)

        super().save(*args, **kwargs)

    def __str__(self):

        return self.name

class UserArea(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='user_areas'
    )
    area = models.ForeignKey(
        Area,
        on_delete=models.CASCADE,
        related_name='area_users'
    )

    class Meta:
        unique_together = ('user', 'area')

    def save(self, *args, **kwargs):
        if self.user.agency_id != self.area.agency_id:
            raise ValueError(
                "El usuario no pertenece a la agencia del área"
            )
        super().save(*args, **kwargs)

class ProcedureSequence(models.Model):

    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name="procedure_sequences"
    )
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("agency", "year")

    def __str__(self):
        return f"{self.agency.name} - {self.year}"

class Procedure(models.Model):

    code = models.CharField(max_length=20)

    agency = models.ForeignKey(
        Agency,
        on_delete=models.PROTECT,
        related_name="procedures"
    )

    # Documento
    document_type = models.ForeignKey(
        Document,
        on_delete=models.PROTECT
    )
    document_number = models.CharField(max_length=50, blank=True, null=True)
    folios = models.PositiveIntegerField(default=0)

    # Remitente
    sender_dni = models.CharField(max_length=15, blank=True, null=True)
    sender_name = models.CharField(max_length=255)
    sender_representante = models.CharField(max_length=255, blank=True, null=True)
    sender_address = models.CharField(max_length=255, blank=True, null=True)
    sender_phone = models.CharField(max_length=20, blank=True, null=True)
    sender_email = models.EmailField(blank=True, null=True)

    from_area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="p_outgoing_flows"
    )

    to_area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        related_name="p_incoming_flows"
    )

    subject = models.TextField()

    is_virtual = models.BooleanField(default=False)

    is_annulled = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_procedures"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    department = models.ForeignKey(Department, on_delete=models.CASCADE, null=True, blank=True)
    province = models.ForeignKey(Province, on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, null=True, blank=True)

    tracking_code = models.CharField(
        max_length=6,
        unique=True,
        null=True,
        blank=True,
        db_index=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['code', 'agency'],
                name='unique_code_per_agency'
            )
        ]

    def __str__(self):
        return self.code

def procedure_file_path(instance, filename):

    procedure = instance.procedure
    agency_id = procedure.agency_id
    code = procedure.code
    ext = filename.split('.')[-1]

    return (
        f"procedures/"
        f"agency_{agency_id}/"
        f"{code}/"
        f"{uuid.uuid4()}.{ext}"
    )

class ProcedureFile(models.Model):

    procedure = models.ForeignKey(
        Procedure,
        on_delete=models.CASCADE,
        related_name="files"
    )

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT
    )

    file = models.FileField(upload_to=procedure_file_path)
    description = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

class ProcedureFlow(models.Model):

    NORMAL = "NR"
    COPY = "CP"

    FLOW_TYPE_CHOICES = [
        (NORMAL, "Normal"),
        (COPY, "Copy"),
    ]

    SENT = "SENT"
    RECEIVED = "RECEIVED"
    FINALIZED = "FINALIZED"
    OBSERVED = "OBSERVED"
    REJECTED = "REJECTED"
    SUBSANATION = "SUBSANATION"
    ANNULLED = "ANNULLED"
    PENDING_SCHEDULE = "PENDING_SCHEDULE"

    STATUS_CHOICES = [
        (SENT, "Sent"),
        (RECEIVED, "Received"),
        (FINALIZED, "Finalized"),
        (OBSERVED, "Observed"),
        (REJECTED, "Rejected"),
        (SUBSANATION, "Subsanation"),
        (ANNULLED, "Annulled"),
        (PENDING_SCHEDULE, "Pending by schedule"),
    ]

    origin_options = models.JSONField(
        null=True,
        blank=True,
        default=list
    )

    procedure = models.ForeignKey(
        Procedure,
        on_delete=models.CASCADE,
        related_name="flows"
    )

    flow_type = models.CharField(
        max_length=2,
        choices=FLOW_TYPE_CHOICES,
        default=NORMAL
    )

    from_area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_flows"
    )

    to_area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        related_name="incoming_flows"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=SENT
    )

    is_to_finalize = models.BooleanField(default=False)
    is_to_observed = models.BooleanField(default=False)
    is_derive = models.BooleanField(default=False)
    
    subject = models.TextField(null=True, blank=True)
    subject_derivar = models.TextField(null=True, blank=True)

    comment = models.TextField(null=True, blank=True)
    sent_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)

    sequence = models.PositiveIntegerField() 

    registered_out_of_schedule_at = models.DateTimeField(
        null=True,
        blank=True
    )
    sent_at = models.DateTimeField(
        null=True, blank=True
    )

    class Meta:

        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["procedure", "sequence"]),
            models.Index(fields=["to_area", "status"]),
        ]

class WorkSchedule(models.Model):
    DAY_CHOICES = [
        (0, "Lunes"),
        (1, "Martes"),
        (2, "Miercoles"),
        (3, "Jueves"),
        (4, "Viernes"),
        (5, "Sabado"),
    ]

    day = models.PositiveSmallIntegerField(choices=DAY_CHOICES, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

class Holiday(models.Model):
    
    date = models.DateField(unique=True)
    description = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

