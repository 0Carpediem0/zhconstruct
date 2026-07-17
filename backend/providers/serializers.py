from rest_framework import serializers

from .models import Provider, ServiceCategory


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ('id', 'name', 'slug', 'description', 'is_active')


class ProviderSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = ('id', 'name', 'slug', 'is_platform_partner')


class ProviderSerializer(serializers.ModelSerializer):
    service_categories = ServiceCategorySerializer(many=True, read_only=True)

    class Meta:
        model = Provider
        fields = (
            'id',
            'name',
            'slug',
            'tax_id',
            'email',
            'phone',
            'is_platform_partner',
            'is_active',
            'service_categories',
        )
