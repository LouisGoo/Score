import csv
import io
import json

import pytest

from score_api.exports.service import audit_state, csv_bytes, safe_cell


@pytest.mark.parametrize(
    "value",
    [
        "=1+1",
        "+cmd",
        "-1+2",
        "@SUM(A1)",
        " \t=1",
        "\rplain",
        "\nplain",
        "\tplain",
        "＝1",
        "\ufeff+1",
        "\x00@x",
    ],
)
def test_formula_cells_are_text(value):
    assert safe_cell(value) == "'" + value


def test_csv_chinese_quoting_zero_and_empty():
    content = csv_bytes(["名称", "分数", "缺交"], [{"名称": '中文,"换行\n对象"', "分数": 0}])
    assert content.startswith(b"\xef\xbb\xbf")
    assert list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")))) == [
        {"名称": '中文,"换行\n对象"', "分数": "0", "缺交": ""}
    ]
    assert safe_cell("001") == "001"


def test_audit_allowlist_rejects_unknown_and_nested_fields():
    state = json.loads(
        audit_state(
            {
                "version": 2,
                "status": {"token": "secret"},
                "credential_hash": "secret",
                "credential_lookup": "secret",
                "token": "secret",
                "nested": {"password": "secret"},
            }
        )
    )
    assert state == {"version": 2}
