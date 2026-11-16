from django.http import JsonResponse
from ..models import SystemLicense

class LicenseMiddleware:

    def __init__(self, get_response):

        self.get_response = get_response

    def __call__(self, request):

        license = SystemLicense.objects.first()

        if license and license.is_expired:

            return JsonResponse({
                "code": "LICENSE_EXPIRED",
                "expired": True,
                "message": license.message,
                "expiration_date": license.expiration_date
            }, status=403)

        return self.get_response(request)