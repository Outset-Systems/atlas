from functools import wraps

import security


def admin_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        if not security.is_admin():
            return security.admins_only()
        return view(*args, **kwargs)
    return guarded


def whole_map_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        if not security.sees_whole_map():
            return security.admins_only()
        return view(*args, **kwargs)
    return guarded


def write_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        refusal = security.write_refusal()
        if refusal:
            return refusal
        return view(*args, **kwargs)
    return guarded
