from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .filters import filter_ticket_queryset
from .models import Ticket
from .permissions import (
    can_assign_employee,
    can_assign_provider,
    can_transition_ticket,
    is_complex_staff_user,
    visible_tickets_for,
)
from .serializers import (
    AssignEmployeeSerializer,
    AssignProviderSerializer,
    ChangeStatusSerializer,
    TicketCreateSerializer,
    TicketReadSerializer,
    TicketStatusHistorySerializer,
    django_validation_details,
)
from .services import apply_initial_routing, assign_employee, assign_provider


class TicketViewSet(ModelViewSet):
    """Командный API заявки без прямого редактирования доменных полей."""

    http_method_names = ('get', 'post', 'head', 'options')

    def create(self, request, *args, **kwargs):
        if not (
            request.user.is_superuser
            or is_complex_staff_user(request.user)
        ):
            raise PermissionDenied(
                'Регистрировать заявки могут только сотрудники ЖК.',
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            TicketReadSerializer(
                serializer.instance,
                context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return TicketCreateSerializer
        if self.action == 'assign_provider':
            return AssignProviderSerializer
        if self.action == 'assign_employee':
            return AssignEmployeeSerializer
        if self.action == 'change_status':
            return ChangeStatusSerializer
        return TicketReadSerializer

    def perform_create(self, serializer):
        ticket = serializer.save()
        serializer.instance = apply_initial_routing(
            ticket,
            changed_by=self.request.user,
        )

    def get_queryset(self):
        queryset = Ticket.objects.select_related(
            'residential_complex',
            'applicant',
            'category',
            'provider',
            'assignee',
        )
        queryset = visible_tickets_for(self.request.user, queryset)
        if self.action != 'list':
            return queryset

        return filter_ticket_queryset(queryset, self.request.query_params)

    def _ticket_response(self, ticket):
        ticket.refresh_from_db()
        return Response(TicketReadSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=('post',), url_path='assign-provider')
    def assign_provider(self, request, pk=None):
        ticket = self.get_object()
        if not can_assign_provider(request.user, ticket):
            raise PermissionDenied('Only complex staff can assign a provider.')

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated_ticket = assign_provider(
                ticket,
                provider=serializer.validated_data['provider'],
                changed_by=request.user,
                comment=serializer.validated_data['comment'],
            )
        except DjangoValidationError as error:
            raise ValidationError(django_validation_details(error)) from error
        return self._ticket_response(updated_ticket)

    @action(detail=True, methods=('post',), url_path='assign-employee')
    def assign_employee(self, request, pk=None):
        ticket = self.get_object()
        if not can_assign_employee(request.user, ticket):
            raise PermissionDenied('Only a provider manager can assign an employee.')

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated_ticket = assign_employee(
                ticket,
                employee=serializer.validated_data['employee'],
            )
        except DjangoValidationError as error:
            raise ValidationError(django_validation_details(error)) from error
        return self._ticket_response(updated_ticket)

    @action(detail=True, methods=('post',), url_path='change-status')
    def change_status(self, request, pk=None):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        if not can_transition_ticket(request.user, ticket, new_status):
            raise PermissionDenied('You cannot perform this status transition.')

        try:
            ticket.transition_to(
                new_status,
                changed_by=request.user,
                comment=serializer.validated_data['comment'],
            )
        except DjangoValidationError as error:
            raise ValidationError(django_validation_details(error)) from error
        return self._ticket_response(ticket)

    @action(detail=True, methods=('get',), url_path='history')
    def history(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketStatusHistorySerializer(
            ticket.status_history.select_related('changed_by'),
            many=True,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
