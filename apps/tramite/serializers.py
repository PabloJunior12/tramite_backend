from rest_framework import serializers
from django.utils.timezone import now
from django.conf import settings
from django.db import transaction
from apps.user.models import User

from .models import ( 

    Company, Area, UserArea, Document, Agency, Procedure, WorkSchedule, Holiday,
    ProcedureFlow, Department, Province, District,
    ProcedureFile,
    ProcedureSequence

)

from .utils import generate_procedure_code, get_next_sequence, get_virtual_areas, check_schedule, ScheduleResult, generate_unique_tracking_code
    

import os

class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "description"]

class ProvinceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Province
        fields = ["id", "description", "department"]

class DistrictSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = ["id", "description", "province"]

class CompanySerializer(serializers.ModelSerializer):

    class Meta:
        model = Company
        fields = '__all__'

    def update(self, instance, validated_data):
        # Verificar si hay un nuevo logo
        new_logo = validated_data.get("logo", None)
        if new_logo and instance.logo:
            # Eliminar el logo anterior del sistema de archivos
            old_logo_path = os.path.join(settings.MEDIA_ROOT, str(instance.logo))
            if os.path.exists(old_logo_path):
                os.remove(old_logo_path)

        instance.logo = new_logo if new_logo else instance.logo  # Mantener el anterior si no se envía nuevo
        instance.name = validated_data.get("name", instance.name)
        instance.ruc = validated_data.get("ruc", instance.ruc)
        instance.address = validated_data.get("address", instance.address)

        instance.save()
        return instance

class AgencySerializer(serializers.ModelSerializer):
    
    class Meta:

        model = Agency
        fields = '__all__'

class AreaSerializer(serializers.ModelSerializer):
    
    agency_name = serializers.CharField(source='agency.name', read_only=True)

    class Meta:

        model = Area
        fields = '__all__'

class MyAreaSerializer(serializers.ModelSerializer):

    area = AreaSerializer()

    class Meta:

        model = UserArea
        fields = '__all__'

class UserAreaSerializer(serializers.ModelSerializer):

    id = serializers.IntegerField(read_only=True)

    # 👉 PARA ESCRIBIR
    area_id = serializers.PrimaryKeyRelatedField(
        source='area',
        queryset=Area.objects.all(),
        write_only=True
    )

    # 👉 PARA LEER
    area = serializers.PrimaryKeyRelatedField(
        read_only=True
    )

    area_name = serializers.CharField(
        source='area.name',
        read_only=True
    )

    area_type = serializers.CharField(
        source='area.type',
        read_only=True
    )

    class Meta:
        model = UserArea
        fields = [
            'id',
            'area',       # lectura (id del área)
            'area_id',    # escritura
            'area_name',
            'area_type',
        ]


class DocumentSerializer(serializers.ModelSerializer):
    
    class Meta:

        model = Document
        fields = '__all__'

class WorkScheduleListSerializer(serializers.ListSerializer):
    def validate(self, data):
        days = [item["day"] for item in data]
        if len(days) != len(set(days)):
            raise serializers.ValidationError(
                "No se puede repetir el mismo día en el horario"
            )
        return data

class WorkScheduleSerializer(serializers.ModelSerializer):

    class Meta:
        model = WorkSchedule
        fields = "__all__"
        list_serializer_class = WorkScheduleListSerializer

        # 🔥 DESACTIVAR UniqueValidator AUTOMÁTICO
        extra_kwargs = {
            "day": {
                "validators": []
            }
        }

    def validate(self, data):
        start = data.get("start_time")
        end = data.get("end_time")

        if start and end and start >= end:
            raise serializers.ValidationError(
                "La hora de inicio debe ser menor que la hora de fin"
            )

        return data

class HolidaySerializer(serializers.ModelSerializer):
    
    class Meta:

        model = Holiday
        fields = '__all__'

# PROCEDURE

class ProcedureCreateSerializer(serializers.Serializer):

    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        required=False,
        allow_null=True
    )
    province = serializers.PrimaryKeyRelatedField(
        queryset=Province.objects.all(),
        required=False,
        allow_null=True
    )
    district = serializers.PrimaryKeyRelatedField(
        queryset=District.objects.all(),
        required=False,
        allow_null=True
    )

    # Documento
    document_type = serializers.PrimaryKeyRelatedField(
        queryset=Document.objects.all()
    )
    document_number = serializers.CharField()
    subject = serializers.CharField()
    folios = serializers.IntegerField()

    # Remitente
    sender_dni = serializers.CharField(required=False, allow_blank=True)
    sender_name = serializers.CharField()
    sender_representante = serializers.CharField(required=False, allow_blank=True)
    sender_address = serializers.CharField(required=False, allow_blank=True)
    sender_phone = serializers.CharField(required=False, allow_blank=True)
    sender_email = serializers.EmailField(required=False, allow_blank=True)

    from_area = serializers.PrimaryKeyRelatedField(
        queryset=Area.objects.all(),
        required=False
    )
    # Destino
    agency = serializers.PrimaryKeyRelatedField(
        queryset=Agency.objects.all()
    )
    destination_areas = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(
            queryset=Area.objects.all()
        ),
        required=False,
        allow_empty=True
    )
    copy_areas = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(
            queryset=Area.objects.all()
        ),
        required=False,
        allow_empty=True
    )

    # Flags
    is_virtual = serializers.BooleanField(default=False)

    def validate(self, data):

        is_virtual = data.get("is_virtual", False)

        destination_areas = set(data.get("destination_areas", []))
        copy_areas = set(data.get("copy_areas", []))

        # 🔒 CASO VIRTUAL
        if is_virtual:
            # No se valida destination_areas
            return data

        # ❌ Un área no puede ser destino y copia
        if destination_areas & copy_areas:
            raise serializers.ValidationError(
                "An area cannot be both destination and copy"
            )

        return data
    
    @transaction.atomic
    def create(self, validated_data):

        request = self.context["request"]
        is_virtual = validated_data.get("is_virtual", False)
        files = request.FILES.getlist("files")
        agency = validated_data["agency"]

        # 🔴 VALIDACIÓN DE HORARIO (NUEVO)
        schedule_status = check_schedule(now())

        if schedule_status == ScheduleResult.NO_LABORABLE:
           raise serializers.ValidationError({
              "error": "Estimado usuario el registro de trámites no está disponible los domingos ni feriados."
           })
        # 🟡 DEFINIR ESTADO INICIAL DEL FLOW
        flow_status = ProcedureFlow.SENT
        registered_out_of_schedule_at = None

        if schedule_status == ScheduleResult.OUT_OF_SCHEDULE:
            flow_status = ProcedureFlow.PENDING_SCHEDULE
            registered_out_of_schedule_at = now()

        # 🔹 Usuario y área por defecto (TU CÓDIGO)
        tracking_code = None
        if is_virtual:

            tracking_code = generate_unique_tracking_code()
            user = User.objects.first()
            from_area, to_area = get_virtual_areas()

            destination_areas = [to_area]
            copy_areas = []

        else:

            user = request.user
            from_area = validated_data.pop("from_area", None)
            destination_areas = validated_data.pop("destination_areas")
            copy_areas = validated_data.pop("copy_areas", [])

        created = []

        for area in destination_areas:

            #  Código correlativo (TU CÓDIGO)
            code = generate_procedure_code(agency)

            # 🧾 Crear trámite (TU CÓDIGO)
            procedure = Procedure.objects.create(
                code=code,
                created_by=user,
                from_area=from_area,
                to_area=area,
                tracking_code=tracking_code,
                **validated_data
            )

            sequence = 1

            # 🔴 FLOW INICIAL (MODIFICADO)
            ProcedureFlow.objects.create(
                procedure=procedure,
                to_area=area,
                sent_by=user,
                sequence=sequence,
                subject=procedure.subject,
                from_area=procedure.from_area,
                flow_type=ProcedureFlow.NORMAL,
                status=flow_status,
                is_active=True,
                registered_out_of_schedule_at=registered_out_of_schedule_at
            )

            # 📎 Archivos (TU CÓDIGO)
            for file in files:
                ProcedureFile.objects.create(
                    procedure=procedure,
                    file=file,
                    uploaded_by=user
                )

            # 📎 Copias (TU CÓDIGO)
            for copy_area in copy_areas:
                ProcedureFlow.objects.create(
                    procedure=procedure,
                    to_area=copy_area,
                    sent_by=user,
                    sequence=sequence,
                    subject=procedure.subject,
                    from_area=procedure.from_area,
                    flow_type=ProcedureFlow.COPY,
                    status=flow_status,   # 🟡 MISMO ESTADO
                    is_active=True
                )

            created.append(procedure)

        return created

class ProcedureUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Procedure
        fields = [
            "document_type",
            "document_number",
            "folios",
            "subject",
            "sender_dni",
            "sender_name",
            "sender_address",
            "sender_phone",
            "sender_email",
            "from_area",
            "to_area",
            "is_virtual",
        ]

    def validate(self, data):

        procedure: Procedure = self.context["procedure"]

        flows_qs = ProcedureFlow.objects.filter(procedure=procedure)

        # ❌ No editable si tiene más de 1 flujo
        if flows_qs.count() > 1:
            raise serializers.ValidationError(
                "Este trámite no se puede editar porque ya tiene más de un flujo"
            )

        return data

    @transaction.atomic
    def update(self, instance, validated_data):

        """
        - Actualiza Procedure
        - Si existe 1 flow, sincroniza subject y to_area
        """

        # 1️⃣ Actualizar Procedure
        procedure = super().update(instance, validated_data)

        # 2️⃣ Obtener el único flujo (si existe)
        flow = (
            ProcedureFlow.objects
            .filter(procedure=procedure)
            .order_by("created_at")
            .first()
        )

        if flow:
            update_fields = []

            if "subject" in validated_data:
                flow.subject = procedure.subject
                update_fields.append("subject")

            if "to_area" in validated_data:
                flow.to_area = procedure.to_area
                update_fields.append("to_area")

            if update_fields:
                flow.save(update_fields=update_fields)

        return procedure

class ProcedureFileSerializer(serializers.ModelSerializer):

    file_name = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ProcedureFile
        fields = ("id", "file_name", "file_url", "created_at")

    def get_file_name(self, obj):
        return obj.file.name.split("/")[-1]

    def get_file_url(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url)

class ProcedureCopySerializer(serializers.ModelSerializer):

    area = AreaSerializer(source="to_area")

    class Meta:
        model = ProcedureFlow
        fields = (
            "id",
            "area",
            "status",
            "created_at",
        )

class ProcedureListSerializer(serializers.ModelSerializer):

    files = ProcedureFileSerializer(many=True, read_only=True)
    from_area = AreaSerializer()
    to_area = AreaSerializer()
    document_type = DocumentSerializer()

    copies = serializers.SerializerMethodField()  # 👈 CLAVE

    class Meta:
        model = Procedure
        fields = '__all__'

    def get_copies(self, obj):
        copies = (
            ProcedureFlow.objects
            .filter(
                procedure=obj,
                flow_type=ProcedureFlow.COPY
            )
            .select_related("to_area")
            .order_by("sequence")
        )
        return ProcedureCopySerializer(copies, many=True).data

class ProcedureAnnulSerializer(serializers.Serializer):

    comment = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):

        procedure: Procedure = self.context["procedure"]

        flows = ProcedureFlow.objects.filter(procedure=procedure)

        if flows.count() > 1:
            raise serializers.ValidationError(
                "Este trámite no se puede editar porque ya tiene más de un flujo"
            )

        return data

    @transaction.atomic
    def save(self):

        procedure: Procedure = self.context["procedure"]
        comment = self.validated_data.get("comment", "")

        # 1️⃣ Marcar trámite como anulado
        procedure.is_annulled = True

        procedure.save(
            update_fields=["is_annulled"]
        )

        # 2️⃣ Actualizar flujo
        flow = ProcedureFlow.objects.get(procedure=procedure)

        flow.status = ProcedureFlow.ANNULLED
        flow.comment = comment
        flow.is_active = False
        flow.save(
            update_fields=["status", "comment", "is_active"]
        )

        return procedure

class ProcedureUpdateCopiesSerializer(serializers.Serializer):

    copy_areas = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(
            queryset=Area.objects.all()
        ),
        allow_empty=True
    )

# PROCEDURE FLOW

class ProcedureFlowSerializer(serializers.ModelSerializer):

    procedure = ProcedureListSerializer()
    from_area = AreaSerializer()
    to_area = AreaSerializer()
    is_copy = serializers.SerializerMethodField()

    class Meta:

        model = ProcedureFlow
        fields = '__all__'

    def get_is_copy(self, obj):

        return obj.flow_type == ProcedureFlow.COPY

# RECEPCIONAR
class ReceiveFlowSerializer(serializers.Serializer):

    def validate(self, data):

        flow: ProcedureFlow = self.context["flow"]
        request = self.context["request"]

        # Debe estar enviado
        if flow.status != ProcedureFlow.SENT:
            raise serializers.ValidationError("The procedure is not pending reception")

        # Área correcta
        area_id = request.headers.get("X-Area-Id")
        if str(flow.to_area_id) != str(area_id):
            raise serializers.ValidationError("You cannot receive a procedure from another area")

        return data

    @transaction.atomic
    def save(self):

        flow: ProcedureFlow = self.context["flow"]
        user = self.context["request"].user

        procedure = flow.procedure

        # 🔒 Desactivar flow NORMAL activo
        flow.is_active = False
        flow.save(update_fields=["is_active"])

        # ➕ Crear nuevo flow RECEIVED
        new_flow = ProcedureFlow.objects.create(
            procedure=procedure,
            sequence=get_next_sequence(procedure),
            flow_type=flow.flow_type,
            status=ProcedureFlow.RECEIVED,
            to_area=flow.to_area,
            sent_by=user,
            is_active=True,
            subject=flow.subject,
            subject_derivar=flow.subject_derivar,
            from_area=flow.from_area,
            is_to_finalize=flow.is_to_finalize,
            origin_options=flow.origin_options,
            is_to_observed=flow.is_to_observed,
            is_derive=flow.is_derive,
        )

        return new_flow

# DERVIVAR
class DeriveFlowSerializer(serializers.Serializer):
    
    origin_options = serializers.JSONField(required=False)

    destination_areas = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Area.objects.all()),
        allow_empty=False
    )
    copy_areas = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Area.objects.all()),
        required=False
    )
    subject_derivar = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):

        flow: ProcedureFlow = self.context["flow"]
        request = self.context["request"]

        # Debe estar recepcionado
        if flow.status != ProcedureFlow.RECEIVED:
            raise serializers.ValidationError("The procedure must be received before deriving")

        # Área correcta
        area_id = request.headers.get("X-Area-Id")
        if str(flow.to_area_id) != str(area_id):
            raise serializers.ValidationError("You cannot derive from another area")

        # No duplicar áreas
        dest = set(a.id for a in data["destination_areas"])
        copies = set(a.id for a in data.get("copy_areas", []))
        if dest & copies:
            raise serializers.ValidationError("An area cannot be destination and copy")

        return data

    @transaction.atomic
    def save(self):

        request = self.context["request"]
        flow: ProcedureFlow = self.context["flow"]
        user = request.user
        procedure = flow.procedure

        dest_areas = self.validated_data["destination_areas"]
        copy_areas = self.validated_data.get("copy_areas", [])
        subject_derivar = self.validated_data.get("subject_derivar", "")

        origin_options = self.validated_data.get("origin_options", [])

        is_special_origin = bool(
            {"AUTHORIZED", "INFO"} & set(origin_options)
        )
        files = request.FILES.getlist("files")
        # 🔒 Desactivar NORMAL activo previo
        flow.is_active = False
        flow.save(update_fields=["is_active"])

        created = []

        # ➡️ Crear flows NORMAL (SENT)
        for area in dest_areas:
            created.append(
                ProcedureFlow.objects.create(
                    procedure=procedure,
                    sequence=get_next_sequence(procedure),
                    flow_type=ProcedureFlow.NORMAL,
                    status = ProcedureFlow.SENT,
                    from_area=flow.to_area,
                    to_area=area,
                    sent_by=user,
                    subject=flow.subject,
                    subject_derivar=subject_derivar,
                    is_active=True,
                    is_to_finalize = is_special_origin,
                    origin_options = origin_options,
                    is_derive = True
                )
            )

        # 📎 Archivos (uno por trámite)
        for file in files:
            ProcedureFile.objects.create(
                procedure=procedure,
                file=file,
                uploaded_by=user
            )

        # 📎 Crear flows COPY (SENT)
        for area in copy_areas:
            created.append(
                ProcedureFlow.objects.create(
                    procedure=procedure,
                    sequence=1,
                    flow_type=ProcedureFlow.COPY,
                    status=ProcedureFlow.SENT,
                    from_area=flow.to_area,
                    to_area=area,
                    sent_by=user,
                    subject=subject_derivar,
                    subject_derivar=subject_derivar,
                    is_to_finalize = is_special_origin,
                    origin_options = origin_options,
                    is_derive = True
                )
            )

        return created
    
# FINALIZAR
class FinalizeFlowSerializer(serializers.Serializer):

    def validate(self, data):
        flow: ProcedureFlow = self.context["flow"]
        request = self.context["request"]

        if flow.status != ProcedureFlow.RECEIVED:
            raise serializers.ValidationError("Only received procedures can be finalized")

        area_id = request.headers.get("X-Area-Id")
        if str(flow.to_area_id) != str(area_id):
            raise serializers.ValidationError("You cannot finalize from another area")

        return data

    def save(self):

        flow: ProcedureFlow = self.context["flow"]
        user = self.context["request"].user
        procedure = flow.procedure

        #  Desactivar NORMAL activo
        flow.is_active = False
        flow.save(update_fields=["is_active"])

        #  Crear flow FINALIZED
        new_flow = ProcedureFlow.objects.create(
            procedure=procedure,
            sequence=get_next_sequence(procedure),
            flow_type=flow.flow_type,
            status=ProcedureFlow.FINALIZED,
            from_area=flow.to_area,
            to_area=flow.to_area,
            sent_by=user,
            is_active=True,
            subject=flow.subject,
            subject_derivar=flow.subject_derivar,
            is_derive = flow.is_derive
        )

        return new_flow

# RECHAZAR 
class RejectFlowSerializer(serializers.Serializer):

    comment = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):

        flow: ProcedureFlow = self.context["flow"]
        request = self.context["request"]

        # Solo se rechaza una rama SENT activa
        if flow.status != ProcedureFlow.SENT or not flow.is_active:
            raise serializers.ValidationError("Only active sent procedures can be rejected")

        # Validar área activa
        area_id = request.headers.get("X-Area-Id")
        if str(flow.to_area_id) != str(area_id):
            raise serializers.ValidationError("You cannot reject from another area")

        return data

    def save(self):

        flow: ProcedureFlow = self.context["flow"]
        user = self.context["request"].user
        procedure = flow.procedure

        # 🔒Cerrar SOLO esta rama (NO todas)
        flow.is_active = False
        flow.save(update_fields=["is_active"])

        #  Crear flow REJECTED (evento)
        rejected_flow = ProcedureFlow.objects.create(
            procedure=procedure,
            sequence=get_next_sequence(procedure),
            flow_type=flow.flow_type,
            status=ProcedureFlow.REJECTED,
            from_area=flow.to_area,   # 👈 quien rechaza
            to_area=flow.to_area,     # 👈 quien ejecuta la acción
            comment=self.validated_data.get("comment", ""),
            is_active=True,        
            subject=flow.subject,
            subject_derivar=flow.subject_derivar,
            sent_by=user,
            is_to_finalize=flow.is_to_finalize,
            origin_options=flow.origin_options,
            is_derive = flow.is_derive
        )

        return rejected_flow

# OBSERVAR 
class ObservedFlowSerializer(serializers.Serializer):

    comment = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):

        flow: ProcedureFlow = self.context["flow"]
        request = self.context["request"]

        if flow.status != ProcedureFlow.RECEIVED:
            raise serializers.ValidationError("Only sent procedures can be observed")

        area_id = request.headers.get("X-Area-Id")
        if str(flow.to_area_id) != str(area_id):
            raise serializers.ValidationError("You cannot operate from another area")

        return data

    def save(self):

        flow: ProcedureFlow = self.context["flow"]
        user = self.context["request"].user
        procedure = flow.procedure

        # 🔒 Desactivar NORMAL activo
        flow.is_active = False
        flow.save(update_fields=["is_active"])

        # ⚠️ Crear flow OBSERVED o REJECTED
        new_flow = ProcedureFlow.objects.create(
            procedure=procedure,
            sequence=get_next_sequence(procedure),
            flow_type=flow.flow_type,
            status=ProcedureFlow.OBSERVED,
            from_area=flow.to_area,   # 👈 quien rechaza
            to_area=flow.to_area,     # 👈 quien ejecuta la acción
            comment=self.validated_data.get("comment", ""),
            is_active=True,          # 👈 RECHAZO NUNCA ES ACTIVO
            subject=flow.subject,
            subject_derivar=flow.subject_derivar,
            sent_by=user,
            is_to_finalize=flow.is_to_finalize,
            origin_options=flow.origin_options,
            is_derive = flow.is_derive
        )

        return new_flow

#  REENVIAR
class ResendObservedFlowSerializer(serializers.Serializer):

    # Flujo
    destination_area = serializers.PrimaryKeyRelatedField(
        queryset=Area.objects.all()
    )
    subject = serializers.CharField(required=False, allow_blank=True)
    subject_derivar = serializers.CharField(required=False, allow_blank=True)


    # Corrección del expediente
    document_type = serializers.PrimaryKeyRelatedField(
        queryset=Document.objects.all(),
        required=False
    )

    document_number = serializers.CharField(required=False, allow_blank=True)
    folios = serializers.IntegerField(required=False, min_value=0)

    def validate(self, data):
        flow: ProcedureFlow = self.context["flow"]

        if flow.status != ProcedureFlow.OBSERVED:
            raise serializers.ValidationError(
                "Only observed procedures can be resent"
            )

        return data

    def save(self):

        request = self.context["request"]
        flow: ProcedureFlow = self.context["flow"]
        user = request.user
        procedure = flow.procedure

        # 🔒 Cerrar flow observado
        flow.is_active = False
        flow.save(update_fields=["is_active"])

        if not flow.is_derive:

            # ACTUALIZAR PROCEDURE (SOLO CAMPOS PERMITIDOS)

            editable_fields = [
                "document_type",
                "document_number",
                "folios",
            ]

            updated_fields = []

            for field in editable_fields:
                if field in self.validated_data:
                    setattr(procedure, field, self.validated_data[field])
                    updated_fields.append(field)

            if updated_fields:
                procedure.save(update_fields=updated_fields)

            # 📎 Archivos de corrección (solo agregar)
            for file in request.FILES.getlist("files"):
                ProcedureFile.objects.create(
                    procedure=procedure,
                    file=file,
                    uploaded_by=user
                )

        #  Crear nuevo flow SENT
        active_area_id = int(request.headers.get("X-Area-Id"))
        active_area = Area.objects.get(id=active_area_id)
        destination_area = self.validated_data["destination_area"]
        subject = self.validated_data.get("subject", None)
        subject_derivar = self.validated_data.get("subject_derivar", None)

        new_flow = ProcedureFlow.objects.create(
            procedure=procedure,
            sequence=get_next_sequence(procedure),
            flow_type=ProcedureFlow.NORMAL,
            status=ProcedureFlow.SENT,
            from_area=active_area,
            to_area=destination_area,
            comment=flow.comment,
            is_active=True,
            subject=subject,
            subject_derivar=subject_derivar,
            sent_by=user,
            is_to_finalize=flow.is_to_finalize,
            origin_options=flow.origin_options,
            is_to_observed=True,
            is_derive=flow.is_derive,
        )

        return new_flow
