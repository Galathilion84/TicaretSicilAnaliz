from app.services.session_manager import (
    parse_rows, select_key_announcements, mask_email, _env_quote, build_search_data,
)

HTML = """
<table>
<tr><th>Başlık</th></tr>
<tr><td>ANKARA</td><td>123</td><td>ACME A.Ş.</td><td>01.02.2025</td><td>11000</td><td>5</td><td>Sermaye Artırımı</td>
    <td><a href="pdf_goster.php?g=abc">PDF</a></td></tr>
<tr><td>kısa</td><td>satır</td></tr>
</table>
"""


def test_parse_rows_extracts_fields_and_pdf_link():
    rows = parse_rows(HTML)
    assert len(rows) == 1
    r = rows[0]
    assert (r["mudurluk"], r["unvan"], r["sayi"], r["tur"]) == ("ANKARA", "ACME A.Ş.", "11000", "Sermaye Artırımı")
    assert r["pdf_url"].endswith("/view/hizlierisim/pdf_goster.php?g=abc") and r["has_pdf"]


def test_parse_rows_min_cells():
    assert parse_rows(HTML, min_cells=9) == []


def test_select_key_announcements_picks_distinct_targets():
    anns = [
        {"id": "new", "tur": "Genel Kurul"},
        {"id": "cap", "tur": "Sermaye Artırımı"},
        {"id": "old", "tur": "Kuruluş"},
    ]
    assert set(select_key_announcements(anns)) == {"new", "cap", "old"}


def test_select_key_announcements_single():
    assert list(select_key_announcements([{"id": "only", "tur": "X"}])) == ["only"]


def test_mask_email():
    assert mask_email("ahmet@firma.com") == "a***@firma.com"


def test_env_quote_roundtrips_through_dotenv():
    from io import StringIO
    from dotenv import dotenv_values
    tricky = r'p"a\ss #1 $x'
    line = "K=" + _env_quote(tricky) + chr(10)
    assert dotenv_values(stream=StringIO(line))["K"] == tricky


def test_build_search_data_dates():
    d = build_search_data("", " X ", "", "01.01.2025", "")
    assert d["TicaretUnvani"] == "X" and d["Tarih"] == "1" and d["Tarih1"] == "01.01.2025"
