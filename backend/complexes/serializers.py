from rest_framework import serializers

from providers.serializers import ProviderSummarySerializer, ServiceCategorySerializer

from .models import ResidentialComplex, ServiceRoutingRule


class ServiceRoutingRuleSerializer(serializers.ModelSerializer):
    category = ServiceCategorySerializer(read_only=True)
    provider = ProviderSummarySerializer(read_only=True)
    mode_label = serializers.CharField(source='get_mode_display', read_only=True)

    class Meta:
        model = ServiceRoutingRule
        fields = ('id', 'category', 'mode', 'mode_label', 'provider', 'is_active')


class ResidentialComplexSerializer(serializers.ModelSerializer):
    routing_rules = ServiceRoutingRuleSerializer(many=True, read_only=True)

    class Meta:
        model = ResidentialComplex
        fields = ('id', 'name', 'slug', 'address', 'is_active', 'routing_rules')
