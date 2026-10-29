from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from complexes.models import ResidentialComplex
from complexes.serializers import ResidentialComplexSerializer
from providers.models import Provider, ServiceCategory
from providers.serializers import ProviderSummarySerializer, ServiceCategorySerializer
from users.serializers import UserSummarySerializer

from .models import Applicant, Ticket, TicketStatusHistory
from resident_portal.models import ServiceOrderDetails
from .permissions import can_register_ticket


def django_validation_details(error):
    return getattr(error, 'message_dict', {'non_field_errors': error.messages})


class ApplicantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Applicant
        fields = (
            'id',
            'full_name',
            'phone',
            'email',
            'apartment',
            'external_id',
        )


class ServiceOrderDetailsSerializer(serializers.ModelSerializer):
    offering_title = serializers.CharField(source='offering.title', read_only=True)
    provider_name = serializers.CharField(
        source='offering.provider.name',
        read_only=True,
    )

    class Meta:
        model = ServiceOrderDetails
        fields = (
            'offering', 'offering_title', 'provider_name', 'scheduled_date',
            'scheduled_start', 'scheduled_end', 'quoted_price', 'currency',
            'resident_comment', 'resident_confirmed_at',
        )


class TicketReadSerializer(serializers.ModelSerializer):
    residential_complex = ResidentialComplexSerializer(read_only=True)
    applicant = ApplicantSerializer(read_only=True)
    category = ServiceCategorySerializer(read_only=True)
    provider = ProviderSummarySerializer(read_only=True)
    assignee = UserSummarySerializer(read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    priority_label = serializers.CharField(source='get_priority_display', read_only=True)
    source_label = serializers.CharField(source='get_source_display', read_only=True)
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)
    service_order = ServiceOrderDetailsSerializer(read_only=True)

    class Meta:
        model = Ticket
        fields = (
            'id',
            'residential_complex',
            'applicant',
            'title',
            'description',
            'category',
            'provider',
            'assignee',
            'status',
            'status_label',
            'priority',
            'priority_label',
            'source',
            'source_label',
            'kind',
            'kind_label',
            'service_order',
            'external_id',
            'created_at',
            'updated_at',
        )


class TicketCreateSerializer(serializers.ModelSerializer):
    applicant = serializers.PrimaryKeyRelatedField(
        queryset=Applicant.objects.filter(is_active=True),
    )
    residential_complex = serializers.PrimaryKeyRelatedField(
        queryset=ResidentialComplex.objects.filter(is_active=True),
    )
    category = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.filter(is_active=True),
    )

    class Meta:
        model = Ticket
        fields = (
            'id',
            'residential_complex',
            'applicant',
            'title',
            'description',
            'category',
            'priority',
        )
        read_only_fields = ('id',)

    def validate(self, attrs):
        request = self.context['request']
        applicant = attrs['applicant']
        residential_complex = attrs['residential_complex']

        if not can_register_ticket(
            request.user,
            residential_complex.pk,
        ):
            raise serializers.ValidationError(
                {'applicant': 'Нельзя зарегистрировать заявку этого заявителя.'}
            )

        candidate = Ticket(source=Ticket.Source.DIRECT, **attrs)
        try:
            candidate.full_clean()
        except DjangoValidationError as error:
            raise serializers.ValidationError(django_validation_details(error)) from error
        return attrs

    def create(self, validated_data):
        return Ticket.objects.create(source=Ticket.Source.DIRECT, **validated_data)


class TicketStatusHistorySerializer(serializers.ModelSerializer):
    changed_by = UserSummarySerializer(read_only=True)
    from_status_label = serializers.CharField(
        source='get_from_status_display',
        read_only=True,
    )
    to_status_label = serializers.CharField(
        source='get_to_status_display',
        read_only=True,
    )

    class Meta:
        model = TicketStatusHistory
        fields = (
            'id',
            'from_status',
            'from_status_label',
            'to_status',
            'to_status_label',
            'changed_by',
            'comment',
            'created_at',
        )


class AssignProviderSerializer(serializers.Serializer):
    provider = serializers.PrimaryKeyRelatedField(
        queryset=Provider.objects.filter(is_active=True),
    )
    comment = serializers.CharField(required=False, allow_blank=True, default='')


class AssignEmployeeSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.filter(is_active=True),
    )


class ChangeStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.Status.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default='')
