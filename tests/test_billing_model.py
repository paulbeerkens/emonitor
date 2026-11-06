import json
from pathlib import Path

import pytest


MODEL_PATH = Path(__file__).parents[1] / "config" / "comed_bill_model.json"


def test_bill_model_reconciles_to_total_bill():
    model = json.loads(MODEL_PATH.read_text())

    modeled_total = (
        model["market_supply_charge_dollars"]
        + sum(model["variable_import_charges_dollars"].values())
        + sum(model["fixed_charges_dollars"].values())
        + sum(model["export_adjustments_dollars"].values())
    )

    assert modeled_total == pytest.approx(146.88)


def test_bill_model_derived_rates():
    model = json.loads(MODEL_PATH.read_text())

    variable_cents_per_kwh = (
        sum(model["variable_import_charges_dollars"].values())
        / model["import_kwh"]
        * 100
    )
    fixed_dollars_per_day = (
        sum(model["fixed_charges_dollars"].values()) / model["billing_days"]
    )

    assert variable_cents_per_kwh == pytest.approx(7.7914379802)
    assert fixed_dollars_per_day == pytest.approx(0.803125)
