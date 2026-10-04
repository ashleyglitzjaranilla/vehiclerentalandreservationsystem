"""The reports page and the CSV export."""

from __future__ import annotations

import csv
import io
from datetime import datetime


def test_reports_page_shows_the_three_summary_tables(admin_client, sample_vehicle):
    response = admin_client.get("/admin/reports")
    assert response.status_code == 200
    assert b"Vehicles by status" in response.data
    assert b"Vehicles by type" in response.data
    assert b"Vehicles by year acquired" in response.data
    # The single sample vehicle was acquired in 2021.
    assert b"2021" in response.data


def test_reports_page_requires_login(client):
    assert client.get("/admin/reports").status_code == 302


def test_csv_export_returns_a_downloadable_file(admin_client, sample_vehicle):
    response = admin_client.get("/admin/reports/export.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]

    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert rows[0][1] == "plate_number"
    assert rows[1][1] == "ABC 1234"
    assert rows[1][2] == "Toyota"


# -- regression tests for the clock migration --------------------------------
#
# reports.py used to call datetime.now(timezone.utc) directly at both of these
# call sites. Reverting either one back to that pre-phase-2 form passed all
# 204 tests, because nothing asserted on the rendered timestamp or the CSV
# filename -- only that a report/export happened at all. These pin both.


def test_the_reports_page_shows_the_clocks_time_with_a_pht_suffix(admin_client, sample_vehicle, monkeypatch):
    fixed_now = datetime(2026, 3, 10, 14, 30)
    monkeypatch.setattr("rental.reports.now", lambda: fixed_now)

    response = admin_client.get("/admin/reports")
    assert response.status_code == 200
    # generated_at.strftime('%d %b %Y %H:%M') + " PHT", from the template.
    assert b"10 Mar 2026 14:30 PHT" in response.data


def test_the_csv_filename_date_comes_from_the_clock(admin_client, sample_vehicle, monkeypatch):
    fixed_now = datetime(2026, 3, 10, 14, 30)
    monkeypatch.setattr("rental.reports.now", lambda: fixed_now)

    response = admin_client.get("/admin/reports/export.csv")
    assert response.status_code == 200
    assert 'filename="vehicles-20260310.csv"' in response.headers["Content-Disposition"]
