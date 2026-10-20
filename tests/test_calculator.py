"""The calculator is unchanged: same page, same fee engine, same result for the reference example."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "public" / "static" / "js" / "estimator.js"
# Hash of estimator.js as it was in the initial commit; any change to fee rules must be deliberate
ENGINE_SHA256 = "feeb3cb712a8512cde53a6418ad3d51f9f3e810c51a626c6293ee2a5e742f953"


def test_calculator_page_loads_the_fee_engine(make_user):
    page = make_user("ali").get("/").get_data(as_text=True)
    assert "estimator.js" in page and 'id="form"' in page and "Fee calculator" in page


def test_estimator_js_is_served(make_user):
    resp = make_user("ali").get("/static/js/estimator.js")
    assert resp.status_code == 200 and resp.data == ENGINE.read_bytes()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_reference_estimate_total_is_unchanged():
    example = {"txn": "nrt", "vehicle": "car", "cc": "1300", "invoiceValue": "5200000", "filer": True,
               "invoiceDate": "2026-07-01", "regDate": "2026-10-20"}
    script = f"console.log(require({json.dumps(str(ENGINE))}).compute({json.dumps(example)}).total)"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=30)  # noqa: S603, S607
    assert out.stdout.strip() == "408190"


def test_fee_engine_file_not_modified_by_this_upgrade():
    assert hashlib.sha256(ENGINE.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == ENGINE_SHA256
