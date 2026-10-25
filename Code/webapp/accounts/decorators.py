from functools import wraps

from django.core.exceptions import PermissionDenied


def permission_required(permission: str):
    """Role check for a view or API route (signed-in users without the permission get 403)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.can(permission):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        wrapper.required_permission = permission
        return wrapper

    return decorator
