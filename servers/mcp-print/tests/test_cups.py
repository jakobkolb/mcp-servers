import pytest
from mcp_print.cups import Cups, check_printer_name, job_printer

PDF = b"%PDF-1.4 fake"


def test_printers_parse_state_acceptance_and_reason(fake_cups):
    assert fake_cups.cups().printers() == [
        {"name": "Office-Laser", "state": "idle", "accepting": True},
        {"name": "Kitchen", "state": "printing", "accepting": True},
        {"name": "Old", "state": "disabled", "accepting": False, "reason": "out of toner"},
    ]


def test_no_printers_is_an_empty_list_not_an_error(fake_cups):
    fake_cups.state["printers"] = []
    assert fake_cups.cups().printers() == []


def test_default_printer(fake_cups):
    assert fake_cups.cups().default_printer() == "Office-Laser"
    fake_cups.state["default"] = None
    assert fake_cups.cups().default_printer() == ""


def test_commands_run_in_the_c_locale(fake_cups):
    fake_cups.cups().printers()
    assert {c["lang"] for c in fake_cups.calls} == {"C"}


def test_submit_sends_the_pdf_on_stdin_with_options(fake_cups):
    job = fake_cups.cups().submit(
        PDF, "Office-Laser", copies=2, title="Brief", sides="two-sided-long-edge", media="A4"
    )
    assert job == "Office-Laser-7"
    [call] = fake_cups.calls
    assert call["cmd"] == "lp"
    assert call["args"] == [
        "-d", "Office-Laser", "-n", "2", "-t", "Brief",
        "-o", "sides=two-sided-long-edge", "-o", "media=A4",
    ]  # fmt: skip
    assert call["stdin"] == PDF.decode()


def test_submit_reports_cups_errors(fake_cups):
    with pytest.raises(RuntimeError, match="not accepting jobs"):
        fake_cups.cups().submit(PDF, "Old")
    with pytest.raises(RuntimeError, match="does not exist"):
        fake_cups.cups().submit(PDF, "Nope")


def test_title_cannot_add_lines(fake_cups):
    fake_cups.cups().submit(PDF, "Office-Laser", title="a\nb")
    assert fake_cups.calls[0]["args"][5] == "a b"


@pytest.mark.parametrize("sides", ["two-sided", "-o", ""])
def test_unknown_sides_are_rejected(fake_cups, sides):
    if sides == "":
        fake_cups.cups().submit(PDF, "Office-Laser", sides=sides)  # empty means printer default
        assert "-o" not in fake_cups.calls[0]["args"]
    else:
        with pytest.raises(ValueError):
            fake_cups.cups().submit(PDF, "Office-Laser", sides=sides)


def test_jobs(fake_cups):
    cups = fake_cups.cups()
    assert [j["job_id"] for j in cups.jobs()] == ["Office-Laser-3", "Kitchen-4"]
    assert cups.jobs("Kitchen") == [
        {
            "job_id": "Kitchen-4",
            "printer": "Kitchen",
            "user": "root",
            "bytes": 1024,
            "submitted": "Thu Oct 15 21:03:55 2026",
        }
    ]
    assert [j["job_id"] for j in cups.jobs(completed=True)] == ["Old-1"]
    with pytest.raises(RuntimeError, match="Invalid destination"):
        cups.jobs("Nope")


def test_cancel(fake_cups):
    cups = fake_cups.cups()
    cups.cancel("Kitchen-4")
    assert fake_cups.calls[-1]["args"] == ["Kitchen-4"]
    with pytest.raises(RuntimeError, match="does not exist"):
        cups.cancel("Kitchen-99")


@pytest.mark.parametrize("name", ["-oraw", "--help", "a b", "a/b", "", "x" * 200, "a\nb"])
def test_names_that_could_become_options_are_rejected(name):
    with pytest.raises(ValueError):
        check_printer_name(name)


@pytest.mark.parametrize(
    ("job", "printer"), [("Office-Laser-12", "Office-Laser"), ("Kitchen-4", "Kitchen")]
)
def test_job_printer(job, printer):
    assert job_printer(job) == printer


@pytest.mark.parametrize("job", ["-a", "Kitchen", "Kitchen-", "-4", "Kitchen-4 -a", "all"])
def test_invalid_job_ids_never_reach_cancel(fake_cups, job):
    with pytest.raises(ValueError):
        fake_cups.cups().cancel(job)
    assert fake_cups.calls == []


def test_missing_client_is_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="not installed"):
        Cups(env={"PATH": str(tmp_path)}).default_printer()
