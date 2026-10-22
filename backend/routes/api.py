"""JSON API used by the calculator page. Every endpoint needs a signed-in user."""
from flask import Blueprint, g, jsonify, request

from ..permissions import is_admin
from ..security import api_login_required
from ..services import estimates

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    from ..db import get_db
    get_db().execute("SELECT 1").fetchone()
    return jsonify(status="ok")


@bp.get("/me")
@api_login_required
def me():
    u = g.user
    return jsonify(id=u["id"], username=u["username"], full_name=u["full_name"],
                   role=u["role"], is_admin=is_admin(u))


@bp.get("/estimates")
@api_login_required
def list_estimates():
    return jsonify(estimates=estimates.list_for(g.user["id"], limit=100))


@bp.post("/estimates")
@api_login_required
def save_estimate():
    try:
        data = estimates.clean(request.get_json(silent=True))
    except estimates.InvalidEstimate as e:
        return jsonify(error=str(e)), 400
    try:
        new_id = estimates.create(g.user["id"], data)
    except estimates.TooManyEstimates:
        return jsonify(error="You've reached the limit of saved estimates. Delete some first."), 409
    return jsonify(estimate=estimates.get_for(g.user["id"], new_id)), 201


@bp.delete("/estimates/<int:estimate_id>")
@api_login_required
def delete_estimate(estimate_id: int):
    if not estimates.delete_for(g.user["id"], estimate_id):
        return jsonify(error="Not found."), 404
    return "", 204
