"""The calculator and each user's saved estimates."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..security import login_required
from ..services import estimates

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def calculator():
    preload = None
    estimate_id = request.args.get("estimate", type=int)
    if estimate_id is not None:
        preload = estimates.get_for(g.user["id"], estimate_id)
        if preload is None:
            abort(404)
    return render_template("app/calculator.html", preload=preload)


@bp.route("/estimates")
@login_required
def saved_estimates():
    rows = estimates.list_for(g.user["id"])
    return render_template("app/estimates.html", estimates=rows)


@bp.route("/estimates/<int:estimate_id>/delete", methods=["POST"])
@login_required
def delete_estimate(estimate_id: int):
    if estimates.delete_for(g.user["id"], estimate_id):
        flash("Estimate deleted.", "ok")
    else:
        abort(404)
    return redirect(url_for("main.saved_estimates"))
