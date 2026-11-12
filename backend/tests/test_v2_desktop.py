"""Offscreen native UI regressions; no real hotspot or phone is touched."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("qrcode")

from tests.test_v2_offline import clock, runtime, sample_snapshot  # noqa: F401,E402


@pytest.fixture
def window(runtime, tmp_path):
    from PySide6.QtWidgets import QApplication

    from attendx.faculty.desktop import FacultyWindow

    application = QApplication.instance() or QApplication([])
    view = FacultyWindow(runtime, models_dir=tmp_path, static_dir=tmp_path)
    view.timer.stop()
    view.sync_timer.stop()
    yield application, view
    view.shutdown()
    view.hide()
    view.deleteLater()
    application.processEvents()


def pump_until(application, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert condition()


def test_roster_refresh_preserves_an_open_faculty_decision_control(window):
    application, view = window
    view.selected_session = view.runtime.start_session(1, 1, 1)["id"]
    view.unlocked_ui()
    view.show()
    view.render_roster()
    combo = view.table.cellWidget(0, 4)
    combo.showPopup()
    application.processEvents()
    assert combo.view().isVisible()
    view.render_roster()
    assert view.table.cellWidget(0, 4) is combo
    assert combo.view().isVisible()
    combo.hidePopup()


def test_system_theme_changes_palette_and_checkbox_has_visible_outline(window):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    from attendx.faculty.theme import ReadableCheckBox

    application, view = window
    box = ReadableCheckBox("Phones are ready", view)
    box.resize(300, 42)
    box.show()
    for scheme, dark in [(Qt.ColorScheme.Dark, True), (Qt.ColorScheme.Light, False)]:
        view.apply_system_theme(scheme)
        application.processEvents()
        assert (view.palette().color(QPalette.ColorRole.Window).lightness() < 128) == dark
        option = QStyleOptionButton()
        box.initStyleOption(option)
        rect = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, box)
        image = box.grab().toImage()
        ratio = image.devicePixelRatio()
        edge = image.pixelColor(int((rect.left() + 1) * ratio), int(rect.center().y() * ratio))
        fill = image.pixelColor(int(rect.center().x() * ratio), int(rect.center().y() * ratio))
        assert abs(edge.lightness() - fill.lightness()) > 35


def test_headcount_dialog_allows_recount_before_final_approval(window):
    from attendx.faculty.review_ui import HeadcountReviewDialog
    from tests.test_v2_offline import finish_marks

    _, view = window
    session = view.runtime.start_session(1, 1, 1)
    finish_marks(view.runtime, session)
    dialog = HeadcountReviewDialog(view.runtime.session(session["id"]), 3, view)
    assert not dialog.approve_button.isEnabled()
    assert dialog.candidates.count() == 1  # The explicit ABSENT row is worth cross-checking.
    dialog.headcount.setValue(2)
    assert dialog.approve_button.isEnabled()
    assert dialog.report["difference"] == 0
    dialog.headcount.setValue(1)
    assert dialog.candidates.count() == 2  # Cross-check the Present rows if physical count is lower.
    assert not dialog.approve_button.isEnabled()
    dialog.reason.setPlainText("Faculty reviewed the discrepancy in person")
    assert dialog.approve_button.isEnabled()
    assert view.runtime.pending_events() == []


def test_attendance_screen_detects_period_without_manual_selection(window):
    _, view = window
    view.unlocked_ui()
    assert view.classes.currentData()["period_number"] == 1
    assert "Period 1" in view.classes.currentText()


def test_start_opens_setup_before_starting_the_five_minute_clock(window, monkeypatch):
    application, view = window
    monkeypatch.setattr(view.hotspot, "status", lambda: "OFF")
    monkeypatch.setattr(view, "_after_hours", lambda: False)
    view.unlocked_ui()
    view.start_class()
    assert view.runtime.store.sessions() == []
    assert view.start_dialog.isVisible()
    pump_until(application, lambda: not view.busy)
    assert view.start_dialog.primary.isEnabled()
    view.start_dialog.reject()


def test_guided_start_prepares_then_opens_the_live_qr(window, monkeypatch):
    from tests.test_v2_start_flow import Hotspot, Listener

    application, view = window
    view.hotspot, view.listener, view.phone_setup = Hotspot(), Listener(), Listener()
    monkeypatch.setattr(view, "_after_hours", lambda: False)
    view.unlocked_ui()
    view.start_class()
    dialog = view.start_dialog
    pump_until(application, lambda: not view.busy)
    dialog.primary.click()
    pump_until(application, lambda: dialog.prepared is not None and not view.busy)
    assert view.runtime.store.sessions() == []
    dialog.confirm.setChecked(True)
    dialog.primary.click()
    pump_until(application, lambda: view.selected_session is not None and not view.busy)
    assert view.runtime.store.session(view.selected_session)["state"] == "COLLECTING"
    assert view.connection_dialog.isVisible()
    assert view.connection_dialog.attendance_qr.pixmap() is not None


def test_repeated_start_reuses_the_current_setup_dialog(window, monkeypatch):
    application, view = window
    monkeypatch.setattr(view.hotspot, "status", lambda: "OFF")
    monkeypatch.setattr(view, "_after_hours", lambda: False)
    view.unlocked_ui()
    view.start_class()
    first = view.start_dialog
    pump_until(application, lambda: not view.busy)
    view.start_class()
    assert view.start_dialog is first
    first.reject()


def test_setup_retry_can_confirm_phone_readiness_again(window, monkeypatch):
    application, view = window
    monkeypatch.setattr(view.hotspot, "status", lambda: "OFF")
    monkeypatch.setattr(view, "_after_hours", lambda: False)
    view.unlocked_ui()
    view.start_class()
    dialog = view.start_dialog
    pump_until(application, lambda: not view.busy)
    prepared = {"phone_ready": False, "password": "test-wifi-9", "address": "192.168.137.1", "cert_dir": "test-certs"}
    dialog.ready(prepared)
    dialog.confirm.setChecked(True)
    dialog.failed("A temporary network error")
    dialog.ready(prepared)
    assert not dialog.confirm.isChecked()
    dialog.confirm.setChecked(True)
    assert dialog.primary.isEnabled()
    dialog.reject()


def test_connection_display_stops_its_timer_and_closes_on_privacy_lock(window):
    _, view = window
    prepared = {"ssid": "Test Wi-Fi", "password": "test-wifi-9", "address": "192.168.137.1", "fingerprint": "test"}
    view.show_connection(prepared=prepared)
    first = view.connection_dialog
    first.accept()
    assert not first.timer.isActive()
    view.show_connection(prepared=prepared)
    current = view.connection_dialog
    assert current.isVisible()
    view.lock_now()
    assert not current.isVisible() and not current.timer.isActive()


@pytest.mark.parametrize("editing", [False, True])
def test_collection_timeout_stops_owned_hotspot_but_keeps_roster(window, clock, monkeypatch, editing):
    from datetime import timedelta

    from tests.test_v2_start_flow import Hotspot

    application, view = window
    view.hotspot = Hotspot()
    view.hotspot.started_by_app = True
    monkeypatch.setattr(view, "_after_hours", lambda: False)
    session = view.runtime.start_session(1, 1, 1)
    view.selected_session = session["id"]
    view.editing = editing
    clock[0] += timedelta(seconds=301)
    view.tick()
    pump_until(application, lambda: not view.hotspot.started_by_app)
    assert view.runtime.store.session(session["id"])["state"] == "REVIEW"
    assert len(view.runtime.store.session(session["id"])["roster"]) == 3


def test_collection_timeout_does_not_wait_for_a_blocked_central_sync(window, clock, monkeypatch):
    from datetime import timedelta

    from tests.test_v2_start_flow import Hotspot

    application, view = window
    view.hotspot = Hotspot()
    view.hotspot.started_by_app = True
    monkeypatch.setattr(view, "_after_hours", lambda: False)
    session = view.runtime.start_session(1, 1, 1)
    view.selected_session = session["id"]
    entered, release = threading.Event(), threading.Event()

    def slow_sync():
        entered.set()
        release.wait(8)

    view.pool.submit(slow_sync)
    assert entered.wait(2)
    view.busy = True
    clock[0] += timedelta(seconds=301)
    try:
        view.tick()
        pump_until(application, lambda: not view.hotspot.started_by_app)
    finally:
        release.set()


def test_detected_period_moves_to_new_class_when_previous_class_is_in_grace(window, clock):
    from datetime import timedelta

    _, view = window
    snapshot = sample_snapshot(clock)
    slot = snapshot["timetable"][0]
    slot.update(period_number=1, start_time="09:00:00", end_time="10:01:00")
    snapshot["timetable"].append({**slot, "period_number": 2, "start_time": "10:01:00", "end_time": "11:00:00"})
    view.runtime.install_snapshot(snapshot)
    view.unlocked_ui()
    assert view.classes.currentData()["period_number"] == 1
    clock[0] += timedelta(minutes=2)
    view.refresh_class_choices()
    assert view.classes.currentData()["period_number"] == 2


def test_qr_fits_its_display_when_resized(window):
    application, _ = window
    from attendx.faculty.classroom_ui import QrLabel
    from attendx.faculty.desktop import qr_pixmap

    label = QrLabel()
    label.setPixmap(qr_pixmap("https://192.168.137.1:9443/classroom#synthetic", 700))
    for width, height in [(260, 180), (180, 260), (400, 400)]:
        label.resize(width, height)
        label.show()
        application.processEvents()
        assert label.pixmap().width() <= label.contentsRect().width()
        assert label.pixmap().height() <= label.contentsRect().height()
        assert label.pixmap().width() == label.pixmap().height()
    label.close()


def test_after_hours_override_expires_at_the_next_teaching_day(window, clock):
    from datetime import timedelta

    _, view = window
    view.override.setChecked(True)
    assert view._override_allowed()
    clock[0] += timedelta(days=1)
    assert not view._override_allowed()


@pytest.mark.parametrize("accepted", [False, True])
def test_cached_unlock_after_hours_requires_a_clear_choice_and_stays_unlocked(window, clock, monkeypatch, accepted):
    from PySide6.QtWidgets import QMessageBox

    _, view = window
    clock[0] = clock[0].replace(hour=18, minute=52)
    view.runtime.privacy_lock()
    view.pin.setText("faculty-pin-9")
    questions = []

    def choose(parent, title, message, *args):
        questions.append(message)
        return QMessageBox.StandardButton.Yes if accepted else QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", choose)
    view.unlock()
    assert questions and "18:00" in questions[0]
    assert view.runtime.unlocked == accepted
    assert view._override_allowed() == accepted
    if accepted:
        view.tick()
        assert view.runtime.unlocked
    else:
        assert view.pin.text() == "faculty-pin-9"


def test_after_hours_online_cancel_preserves_credentials_and_does_not_start_request(window, clock, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _, view = window
    clock[0] = clock[0].replace(hour=18, minute=52)
    view.password.setText("not-sent-9")
    view.pin.setText("faculty-pin-9")
    started = []
    monkeypatch.setattr(view, "task", lambda *args: started.append(args))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    view.provision_online()
    assert not started
    assert view.password.text() == "not-sent-9"
    assert view.pin.text() == "faculty-pin-9"


def test_closing_lock_reason_survives_background_sync_and_override_is_visible_on_sign_in(window, clock):
    _, view = window
    view.show()
    view.unlocked_ui()
    clock[0] = clock[0].replace(hour=18, minute=52)
    view.tick()
    assert not view.runtime.unlocked
    assert "18:00" in view.auth_status.text()
    assert "after hours" in view.auth_status.text().lower()
    assert view.hours_notice.isVisible()
    assert "18:00" in view.hours_notice.text()
    assert view.override.isVisible() and view.auth_tab.isAncestorOf(view.override)
    view.auth_status.setText("Sync: 0 acknowledged, 0 pending.")
    assert "18:00" in view.hours_notice.text()


@pytest.mark.parametrize("local_time,expected", [("17:59:59", False), ("18:00:00", True), ("18:52:00", True)])
def test_closing_time_uses_the_institution_clock(window, clock, local_time, expected):
    from datetime import datetime

    _, view = window
    clock[0] = datetime.fromisoformat(f"{clock[0].date()}T{local_time}")
    assert view._after_hours() == expected


@pytest.mark.parametrize("seconds_after_end", [0, 180, 300])
def test_class_end_reminder_runs_once_during_grace(window, clock, seconds_after_end):
    from datetime import timedelta

    from PySide6.QtCore import QObject, Signal

    class Notifications(QObject):
        shown = Signal(str, str)

        def showMessage(self, title, message):
            self.shown.emit(title, message)

    _, view = window
    snap = sample_snapshot(clock)
    snap["timetable"][0].update(start_time="09:00:00", end_time="10:00:00")
    view.runtime.install_snapshot(snap)
    notifications = Notifications()
    from PySide6.QtTest import QSignalSpy

    spy = QSignalSpy(notifications.shown)
    view.tray = notifications
    clock[0] += timedelta(seconds=seconds_after_end)
    view.remind(snap)
    view.remind(snap)
    assert spy.count() == 1
    assert "10:05" in spy.at(0)[1]


@pytest.mark.parametrize("suppression", ["before_end", "after_grace", "started", "holiday", "cancelled", "other_day"])
def test_class_end_reminder_ignores_ineligible_or_started_meetings(window, clock, suppression):
    from datetime import timedelta

    from PySide6.QtCore import QObject, Signal
    from PySide6.QtTest import QSignalSpy

    class Notifications(QObject):
        shown = Signal(str, str)

        def showMessage(self, title, message):
            self.shown.emit(title, message)

    _, view = window
    snap = sample_snapshot(clock)
    snap["timetable"][0].update(start_time="09:00:00", end_time="10:00:00")
    if suppression == "holiday":
        snap["holidays"] = [{"date": str(clock[0].date()), "name": "Holiday"}]
    if suppression == "cancelled":
        snap["cancelled_classes"] = [
            {"date": str(clock[0].date()), "section_id": 1, "course_id": 1, "period_number": 1}
        ]
    if suppression == "other_day":
        snap["timetable"][0]["weekday"] = (clock[0].weekday() + 1) % 7
    view.runtime.install_snapshot(snap)
    if suppression == "started":
        view.runtime.start_session(1, 1, 1)
    if suppression == "before_end":
        clock[0] -= timedelta(seconds=1)
    if suppression == "after_grace":
        clock[0] += timedelta(seconds=301)
    notifications = Notifications()
    spy = QSignalSpy(notifications.shown)
    view.tray = notifications
    view.remind(snap)
    assert spy.count() == 0


def test_pending_online_provision_cannot_undo_privacy_lock(window, clock, monkeypatch):
    from attendx.faculty import desktop

    application, view = window
    entered, release = threading.Event(), threading.Event()

    class Central:
        def __init__(self, *args, **kw):
            pass

        def provision(self, *args):
            return {"device_id": "test-device", "credential": "test-only"}

        def download(self, *args):
            entered.set()
            assert release.wait(5)
            return sample_snapshot(clock)

    monkeypatch.setattr(desktop, "CentralClient", Central)
    view.pin.setText("faculty-pin-9")
    view.provision_online()
    assert entered.wait(3)
    view.lock_now()
    release.set()
    pump_until(application, lambda: not view.busy)
    assert not view.runtime.unlocked
    assert not view.tabs.isTabEnabled(1)


def test_modal_editing_does_not_suppress_closing_time_lock(window, monkeypatch):
    _, view = window
    view.editing = True
    monkeypatch.setattr(view, "_after_hours", lambda: True)
    view.tick()
    assert not view.runtime.unlocked
    assert not view.tabs.isTabEnabled(1)


def test_shutdown_waits_for_late_owned_hotspot_start_and_stops_it(window):
    _, view = window
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    class Hotspot:
        started_by_app = False

        def start(self, *args):
            entered.set()
            assert release.wait(5)
            self.started_by_app = True
            finished.set()

        def stop_owned(self):
            self.started_by_app = False

    view.hotspot = Hotspot()
    view.start_hotspot()
    assert entered.wait(3)
    threading.Timer(0.05, release.set).start()
    view.shutdown()
    assert finished.wait(3)
    assert not view.hotspot.started_by_app
    assert not view.runtime.unlocked


def test_late_hotspot_start_is_stopped_after_privacy_lock(window):
    application, view = window
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

    class Hotspot:
        started_by_app = False

        def start(self, *args):
            entered.set()
            assert release.wait(5)
            self.started_by_app = True

        def stop_owned(self):
            self.started_by_app = False
            stopped.set()

    view.hotspot = Hotspot()
    view.start_hotspot()
    assert entered.wait(3)
    view.lock_now()
    release.set()
    pump_until(application, lambda: not view.busy and stopped.is_set())
    assert not view.hotspot.started_by_app and not view.runtime.unlocked
