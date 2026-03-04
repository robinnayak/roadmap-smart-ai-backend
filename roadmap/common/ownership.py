from django.http import Http404
from django.shortcuts import get_object_or_404


def get_owned_object_or_404(model, *, user, owner_filter="user", **lookup):
    """
    Resolve a model instance owned by the authenticated user using a dotted owner
    path, for example:
      - owner_filter="user"
      - owner_filter="subgoal__milestone__goal__user"
    """
    if user is None:
        raise Http404("Authentication required")

    scoped_lookup = dict(lookup)
    scoped_lookup[owner_filter] = user
    return get_object_or_404(model, **scoped_lookup)
