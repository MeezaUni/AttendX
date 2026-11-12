"""Native faculty-only Windows application. Run with python -m attendx.faculty.desktop."""

import argparse
import io
import json
import logging
import os
import sys
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import qrcode
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from attendx.config import PROJECT_DIR
from attendx.face.engine import RealFaceEngine
from attendx.faculty.classroom_ui import ConnectionDialog, QrLabel, StartDialog
from attendx.faculty.network import HotspotController, StudentListener, create_tls_material, install_shared_tls
from attendx.faculty.reconciliation import submission_text
from attendx.faculty.review_ui import HeadcountReviewDialog
from attendx.faculty.runtime import FacultyRuntime, parse_stamp
from attendx.faculty.setup import ClassroomSetup, PhoneSetupListener
from attendx.faculty.sync_client import CentralClient
from attendx.faculty.theme import ReadableCheckBox, apply_theme
from attendx.services.collection_timing import START_GRACE_SECONDS, class_bounds

log = logging.getLogger("attendx.faculty")


def resources():
    return Path(getattr(sys, "_MEIPASS", PROJECT_DIR))


def qr_pixmap(text, size=280):
    image = qrcode.make(text)
    data = io.BytesIO()
    image.save(data, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(data.getvalue())
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)


class Bridge(QObject):
    completed = Signal(object, object)
    network_stopped = Signal(str)


class FacultyWindow(QMainWindow):
    def __init__(self, runtime, *, models_dir, static_dir):
        super().__init__()
        self.runtime, self.models_dir, self.static_dir = runtime, models_dir, static_dir
        self.hotspot = HotspotController()
        self.listener = StudentListener(runtime, self.hotspot)
        self.phone_setup = PhoneSetupListener(runtime, self.hotspot)
        self.prepared, self.start_dialog, self.connection_dialog = None, None, None
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.network_cleanup = ThreadPoolExecutor(max_workers=1)
        self.network_lock = threading.RLock()
        self.bridge = Bridge()
        self.bridge.completed.connect(self._completed)
        self.busy, self.selected_session, self.editing, self.last_qr = False, None, False, None
        self.security_epoch = 0
        self.security_lock = threading.RLock()
        self.last_sync = ""
        self.setWindowTitle("AttendX Faculty V2")
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, available.width() - 40), min(820, available.height() - 60))
        icon_path = resources() / "assets" / "attendx.ico"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.auth_tab = QWidget()
        self.attendance_tab = QWidget()
        self.network_tab = QWidget()
        self.tabs.addTab(self.auth_tab, "Sign in && sync")
        self.tabs.addTab(self.attendance_tab, "Attendance")
        self.tabs.addTab(self.network_tab, "Settings")
        self.apply_system_theme()
        QApplication.styleHints().colorSchemeChanged.connect(self.apply_system_theme)
        self._auth_ui()
        self._attendance_ui()
        self._network_ui()
        self._refresh_hours_notice()
        self.bridge.network_stopped.connect(self.network_status.setText)
        self.tabs.setTabEnabled(1, False)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        show = QAction("Open AttendX Faculty", self)
        show.triggered.connect(self.showNormal)
        lock = QAction("Lock and stop classroom intake", self)
        lock.triggered.connect(self.lock_now)
        quit_action = QAction("Quit AttendX Faculty", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(show)
        menu.addAction(lock)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda _: self.showNormal())
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.sync_approved)
        self.sync_timer.start(60000)
        self.statusBar().showMessage("Locked. Provision online first, then use your offline faculty PIN.")
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def line(self, secret=False, value=""):
        widget = QLineEdit(value)
        if secret:
            widget.setEchoMode(QLineEdit.EchoMode.Password)
        return widget

    def apply_system_theme(self, scheme=None):
        self.theme_colors = apply_theme(self, scheme)
        if hasattr(self, "table"):
            self.render_roster()

    def button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _auth_ui(self):
        layout = QVBoxLayout(self.auth_tab)
        title = QLabel("AttendX Faculty")
        title.setStyleSheet("font-size:28px;font-weight:600;color:#1f3a96")
        layout.addWidget(title)
        note = QLabel(
            "Faculty accounts only. First use requires central HTTPS connectivity. "
            "Student credentials and enrollment photographs are never cached here."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.hours_notice = QLabel()
        self.hours_notice.setWordWrap(True)
        layout.addWidget(self.hours_notice)
        self.override = ReadableCheckBox("I am authorized to use AttendX after hours today")
        self.override_day = None
        self.override.toggled.connect(
            lambda enabled: setattr(self, "override_day", self._local_day() if enabled else None)
        )
        self.override.toggled.connect(self._refresh_hours_notice)
        layout.addWidget(self.override)
        form = QFormLayout()
        stored = self.runtime.store.kv_get("central", {})
        self.central_url = self.line(value=stored.get("url", os.environ.get("ATTENDX_CENTRAL_URL", "")))
        self.central_url.setPlaceholderText("Enter the university's configured central HTTPS URL")
        self.username, self.password, self.pin = self.line(), self.line(True), self.line(True)
        self.central_ca = self.line(value=stored.get("ca_bundle", ""))
        form.addRow("Central HTTPS URL", self.central_url)
        form.addRow("Central CA bundle (blank = system trust)", self.central_ca)
        form.addRow("Faculty username", self.username)
        form.addRow("Central faculty password", self.password)
        form.addRow("Local faculty PIN / passphrase (8+ characters)", self.pin)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.button("Provision or reauthorize online", self.provision_online, buttons)
        self.button("Unlock cached faculty profile", self.unlock, buttons)
        self.button("Synchronize approved attendance", self.sync_approved, buttons)
        self.button(
            "Open central CC portal", lambda: webbrowser.open(self.central_url.text().rstrip("/") + "/faculty"), buttons
        )
        layout.addLayout(buttons)
        self.auth_status = QLabel("No faculty session unlocked.")
        self.auth_status.setWordWrap(True)
        layout.addWidget(self.auth_status)
        layout.addStretch()

    def _attendance_ui(self):
        layout = QVBoxLayout(self.attendance_tab)
        top = QHBoxLayout()
        self.classes = QComboBox()
        self.class_choice_override = None
        self.classes.activated.connect(lambda _: setattr(self, "class_choice_override", self.classes.currentData()))
        top.addWidget(QLabel("Detected class"))
        top.addWidget(self.classes, 1)
        self.start_button = self.button("Start attendance · 5 minutes", self.start_class, top)
        self.start_button.setObjectName("primary")
        self.button("Manual roster", self.start_manual, top)
        layout.addLayout(top)
        self.class_hint = QLabel("Your assigned timetable and laptop time choose the period automatically.")
        self.class_hint.setWordWrap(True)
        layout.addWidget(self.class_hint)
        saved = QHBoxLayout()
        saved.addWidget(QLabel("Saved sessions"))
        self.saved_sessions = QComboBox()
        self.saved_sessions.currentIndexChanged.connect(self.select_saved)
        saved.addWidget(self.saved_sessions, 1)
        self.end_button = self.button("End collection", self.close_collection, saved)
        self.end_button.hide()
        self.button("Lock / end of day", self.lock_now, saved)
        layout.addLayout(saved)
        qr_row = QHBoxLayout()
        self.qr = QrLabel(self.attendance_tab)
        self.qr.setMaximumSize(240, 240)
        self.qr.setText("Start attendance to show the classroom QR.")
        self.qr.mousePressEvent = lambda event: self.show_connection(attendance=True)
        # The QR is presented in its own resizable dialog, rather than squeezed
        # between the roster and toolbar on high-DPI laptop displays.
        self.qr.hide()
        self.summary = QLabel("All students begin UNMARKED.")
        self.summary.setWordWrap(True)
        qr_row.addWidget(self.summary, 1)
        layout.addLayout(qr_row)
        connection_actions = QHBoxLayout()
        self.wifi_button = self.button("Show Wi-Fi QR + password", self.show_connection, connection_actions)
        self.attendance_qr_button = self.button(
            "Show large attendance QR", lambda: self.show_connection(attendance=True), connection_actions
        )
        self.wifi_button.hide()
        self.attendance_qr_button.hide()
        layout.addLayout(connection_actions)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Roll number", "Name", "Enrollment", "Submission", "Faculty decision", "Review / reason"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.hide()
        layout.addWidget(self.table, 1)
        approval = QHBoxLayout()
        self.headcount_label = QLabel("Physical classroom headcount")
        approval.addWidget(self.headcount_label)
        self.headcount = QSpinBox()
        self.headcount.setRange(0, 10000)
        self.headcount.editingFinished.connect(self.save_headcount)
        approval.addWidget(self.headcount)
        self.approve_button = self.button("Approve Final Attendance", self.approve, approval)
        self.amend_button = self.button("Amend selected approved student", self.amend, approval)
        for widget in (self.headcount_label, self.headcount, self.approve_button, self.amend_button):
            widget.hide()
        layout.addLayout(approval)
        layout.addStretch()

    def _network_ui(self):
        outer = QVBoxLayout(self.network_tab)
        intro = QLabel(
            "Start attendance automatically prepares the classroom Wi-Fi and secure phone connection. "
            "The app detects the class and period, then stops classroom networking after five minutes."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)
        advanced = QToolButton()
        advanced.setText("Advanced network settings")
        advanced.setCheckable(True)
        outer.addWidget(advanced)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        panel.setVisible(False)
        advanced.toggled.connect(panel.setVisible)
        outer.addWidget(panel)
        outer.addStretch()
        note = QLabel(
            "The student website binds only to a verified Windows Wi-Fi Direct hotspot adapter. "
            "Install and trust the classroom CA on demonstration phones. Camera access must use HTTPS "
            "without bypassing certificate warnings. An existing hotspot is never reconfigured or stopped by AttendX."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        config = self.runtime.store.kv_get("network", {})
        form = QFormLayout()
        self.ssid = self.line(value=config.get("ssid", "AttendX-Classroom"))
        self.wifi_password = self.line(True)
        self.hotspot_ip = self.line(value=config.get("address", "192.168.137.1"))
        self.cert_dir = self.line(value=config.get("cert_dir", str(self.runtime.store.directory / "certs")))
        self.closing = self.line(value=config.get("closing", "18:00"))
        self.trusted = ReadableCheckBox(
            "I installed/trusted the classroom CA on demo phones and verified their HTTPS browser camera"
        )
        form.addRow("Classroom SSID", self.ssid)
        form.addRow("Hotspot WPA password (not saved)", self.wifi_password)
        form.addRow("Hotspot IPv4 address", self.hotspot_ip)
        form.addRow("Certificate directory", self.cert_dir)
        form.addRow("University closing time (HH:MM)", self.closing)
        layout.addLayout(form)
        layout.addWidget(self.trusted)
        row = QHBoxLayout()
        self.button("Probe hotspot", self.probe_hotspot, row)
        self.button("Start application-managed hotspot", self.start_hotspot, row)
        self.button("Create classroom CA and HTTPS certificate", self.create_certificates, row)
        self.button("Start trusted student HTTPS listener", self.start_listener, row)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        self.button("Stop student listener and owned hotspot", self.stop_network, row2)
        self.button("Show Wi-Fi connection QR", self.wifi_qr, row2)
        self.button("Start HTTPS camera check (no intake)", lambda: self.start_listener(True), row2)
        layout.addLayout(row2)
        self.network_status = QLabel("Hotspot and phone trust have not been verified.")
        self.network_status.setWordWrap(True)
        layout.addWidget(self.network_status)
        self.connection_qr = QLabel()
        layout.addWidget(self.connection_qr)
        layout.addStretch()

    def task(self, fn, callback=None):
        if self.busy:
            self.statusBar().showMessage("An operation is already running; wait for its result.")
            return
        self.busy = True
        epoch = self.security_epoch
        self.statusBar().showMessage("Working…")

        def work():
            try:
                result = fn()
                return (result, None, callback, epoch)
            except Exception as exc:
                log.warning("faculty operation failed: %s", type(exc).__name__)
                return (None, str(exc), callback, epoch)

        future = self.pool.submit(work)
        future.add_done_callback(lambda f: self.bridge.completed.emit(f.result(), None))

    def _completed(self, bundle, unused):
        self.busy = False
        result, error, callback, epoch = bundle
        if epoch != self.security_epoch:
            return  # A privacy lock cancels every pending authorization/UI callback.
        if not self.runtime.unlocked and self.tabs.isTabEnabled(1):
            self.lock_now()
        if error:
            self.statusBar().showMessage(error)
            if error.startswith("Classroom start cancelled"):
                return
            if self.start_dialog and self.start_dialog.isVisible():
                self.start_dialog.failed(error)
            QMessageBox.warning(self, "AttendX operation", error)
        else:
            if callback:
                callback(result)
            self.statusBar().showMessage("Operation completed. Approved records remain stored locally.")

    def provision_online(self):
        if not self._allow_sign_in_hours():
            return
        url, username, password, pin = (
            self.central_url.text(),
            self.username.text(),
            self.password.text(),
            self.pin.text(),
        )
        ca = self.central_ca.text().strip()
        epoch = self.security_epoch
        existing = self.runtime.store.kv_get("central", {})
        self.password.clear()
        self.pin.clear()

        def run():
            central = CentralClient(url, ca_bundle=ca or True)
            device = central.provision(
                username, password, os.environ.get("COMPUTERNAME", "faculty-laptop"), existing.get("device_id")
            )
            snap = central.download(device["credential"])
            with self.security_lock:
                if epoch != self.security_epoch:
                    return None
                if self.runtime.store.kv_get("faculty_pin"):
                    self.runtime.refresh_authorization(snap, pin)
                else:
                    self.runtime.provision(snap, pin)
                self.runtime.store.kv_set("central", {"url": url, "ca_bundle": ca, **device})
            # Provision trust while online, so an ordinary offline Start needs no central request.
            network = self.runtime.store.kv_get("network", {})
            install_shared_tls(self.runtime, central, device["credential"], network.get("address", "192.168.137.1"))
            return snap

        self.task(run, lambda _: self.unlocked_ui())

    def unlock(self):
        if not self._allow_sign_in_hours():
            return
        pin = self.pin.text()
        self.pin.clear()
        try:
            self.runtime.unlock(pin)
            self.unlocked_ui()
        except ValueError as exc:
            QMessageBox.warning(self, "Unlock faculty profile", str(exc))

    def unlocked_ui(self):
        snap = self.runtime._require()
        self.refresh_class_choices()
        self.tabs.setTabEnabled(1, True)
        self.auth_status.setText(
            f"{snap['faculty']['name']} · Last roster sync {snap['generated_at']} · "
            f"Offline authorization until {snap['offline_valid_until']} · "
            f"{len(self.runtime.pending_events())} unsynced approved event(s)"
        )
        self.refresh_saved()
        self.tabs.setCurrentIndex(1)
        self.statusBar().showMessage("Faculty profile unlocked. Start the detected class or open a saved roster.")

    def refresh_class_choices(self):
        if self.classes.view().isVisible():
            return
        current = self.class_choice_override
        meetings = self.runtime.available_meetings()
        self.classes.blockSignals(True)
        self.classes.clear()
        for meeting in meetings:
            self.classes.addItem(
                f"{meeting['course']} · {meeting['section']} · Period {meeting['period_number']} "
                f"({meeting['start_time'][:5]}–{meeting['end_time'][:5]})",
                meeting,
            )
        if not meetings:
            self.classes.addItem("No scheduled class available now", None)
        elif current:
            index = next(
                (
                    i
                    for i, m in enumerate(meetings)
                    if all(m[k] == current[k] for k in ("section_id", "course_id", "period_number"))
                ),
                0,
            )
            self.classes.setCurrentIndex(index)
        self.classes.blockSignals(False)
        self.start_button.setEnabled(bool(meetings))
        self.class_hint.setText(
            "Period detected from your timetable. Choose another class only if both are eligible now."
            if len(meetings) > 1
            else "Period detected automatically. You can start until five minutes after class ends."
            if meetings
            else "No class is available now. Check the timetable or review a saved session below."
        )

    make_qr = staticmethod(qr_pixmap)

    @staticmethod
    def wifi_payload(ssid, password):
        def escape(value):
            for char in ("\\", ";", ",", ":", '"'):
                value = value.replace(char, "\\" + char)
            return value

        return f"WIFI:T:WPA;S:{escape(ssid)};P:{escape(password)};;"

    def classroom_flow(self):
        return ClassroomSetup(
            self.runtime,
            self.hotspot,
            self.listener,
            self.phone_setup,
            static_dir=self.static_dir,
            models_dir=self.models_dir,
            lock=self.network_lock,
        )

    def show_connection(self, checked=False, *, prepared=None, attendance=False):
        prepared = prepared or self.prepared
        if not prepared:
            self.statusBar().showMessage("Click Start attendance to prepare the classroom connection first.")
            return
        if self.connection_dialog:
            if self.connection_dialog.isVisible():
                self.connection_dialog.tabs.setCurrentIndex(2 if attendance else 0)
                self.connection_dialog.raise_()
                return
            self.connection_dialog.timer.stop()
            self.connection_dialog.deleteLater()
        parent = self.start_dialog if self.start_dialog and self.start_dialog.isVisible() else self
        self.connection_dialog = ConnectionDialog(self, prepared, attendance=attendance, parent=parent)
        self.connection_dialog.show()

    def sync_approved(self):
        config = self.runtime.store.kv_get("central")
        if not config or self.busy:
            return

        def run():
            client = CentralClient(config["url"], ca_bundle=config.get("ca_bundle") or True)
            result = client.synchronize(self.runtime)
            if self.runtime.unlocked:
                self.runtime.install_snapshot(client.download(config["credential"], runtime=self.runtime))
            return result

        def done(result):
            self.auth_status.setText(
                f"Sync: {result['acknowledged']} acknowledged, {result['pending']} pending. {result['error']}"
            )
            if self.runtime.unlocked:
                self.refresh_saved()

        # Avoid invalidating active classroom challenges in the middle of collection.
        if self.runtime.unlocked and any(s["state"] == "COLLECTING" for s in self.runtime.store.sessions()):
            self.task(
                lambda: CentralClient(config["url"], ca_bundle=config.get("ca_bundle") or True).synchronize(
                    self.runtime
                ),
                done,
            )
        else:
            self.task(run, done)

    def refresh_saved(self):
        self.saved_sessions.blockSignals(True)
        self.saved_sessions.clear()
        for s in self.runtime.list_sessions():
            self.saved_sessions.addItem(f"{s['date']} · {s['course']} · P{s['period_number']} · {s['state']}", s["id"])
        index = self.saved_sessions.findData(self.selected_session)
        self.saved_sessions.setCurrentIndex(max(0, index))
        self.saved_sessions.blockSignals(False)
        self.select_saved()

    def select_saved(self):
        self.selected_session = self.saved_sessions.currentData()
        if self.selected_session and not self.headcount.hasFocus():
            session = self.runtime.session(self.selected_session)
            self.headcount.setValue(session.get("draft_headcount", session.get("headcount", 0)))
        self.render_roster()

    def save_headcount(self):
        if self.selected_session and self.runtime.unlocked:
            try:
                session = self.runtime.session(self.selected_session)
                if session["state"] != "APPROVED":
                    self.runtime.record_headcount(self.selected_session, self.headcount.value())
            except ValueError as exc:
                self.statusBar().showMessage(str(exc))

    def start_class(self):
        if self.start_dialog and self.start_dialog.isVisible():
            self.start_dialog.raise_()
            return
        if not self.runtime.unlocked or not self.classes.currentData():
            return
        if self._after_hours() and not self._override_allowed():
            QMessageBox.warning(
                self, "After hours", "Select the authorized after-hours override before starting a class."
            )
            return
        if self.busy:
            self.statusBar().showMessage("Finishing the current operation; please wait a moment.")
            return
        meeting = self.classes.currentData()
        if meeting.get("session_id"):
            self.selected_session = meeting["session_id"]
            self.refresh_saved()
            self.statusBar().showMessage("Attendance already started for this class. Review its saved roster below.")
            return
        self.start_dialog = StartDialog(self, meeting)
        self.start_dialog.show()

    def start_manual(self):
        if not self.runtime.unlocked or (self._after_hours() and not self._override_allowed()):
            self.statusBar().showMessage("Unlock the faculty profile and check the authorized closing time first.")
            return
        meeting = self.classes.currentData()
        if not meeting:
            return
        if meeting.get("session_id"):
            self.selected_session = meeting["session_id"]
        else:
            try:
                session = self.runtime.start_session(
                    meeting["section_id"], meeting["course_id"], meeting["period_number"]
                )
                self.selected_session = session["id"]
            except ValueError as exc:
                QMessageBox.warning(self, "Manual attendance", str(exc))
                return
        self.refresh_saved()

    def close_collection(self):
        try:
            if self.selected_session:
                self.runtime.close_collection(self.selected_session)
                self.stop_network()
                self.refresh_saved()
        except ValueError as exc:
            QMessageBox.warning(self, "Close collection", str(exc))

    def render_roster(self):
        available = bool(self.selected_session and self.runtime.unlocked)
        self.table.setVisible(available)
        if not available:
            return
        if not self.selected_session or not self.runtime.unlocked or self.editing:
            return
        try:
            s = self.runtime.session(self.selected_session)
        except ValueError:
            return
        collecting, reviewing, approved = s["state"] == "COLLECTING", s["state"] == "REVIEW", s["state"] == "APPROVED"
        self.end_button.setVisible(collecting)
        self.wifi_button.setVisible(collecting and bool(self.prepared))
        self.attendance_qr_button.setVisible(collecting and bool(self.prepared))
        for widget in (self.headcount_label, self.headcount, self.approve_button):
            widget.setVisible(reviewing)
        self.amend_button.setVisible(approved)
        roster_key = (s["id"], tuple(row["student_id"] for row in s["roster"]))
        if getattr(self, "_roster_key", None) != roster_key:
            self.table.setRowCount(0)
            self.table.setRowCount(len(s["roster"]))
            self._roster_key = roster_key
        for index, row in enumerate(s["roster"]):
            review = row["review"]
            values = [
                row["roll_number"],
                row["name"],
                row["enrollment_state"],
                submission_text(row, approved=approved),
                row["status"],
                review["reason"] if review and not review["resolved"] else row["reason"],
            ]
            for col, value in enumerate(values):
                item = self.table.item(index, col)
                if item is None:
                    item = QTableWidgetItem(str(value))
                    self.table.setItem(index, col, item)
                elif item.text() != str(value):
                    item.setText(str(value))
                if col == 4:
                    item.setForeground(QColor(self.theme_colors["text"]))
                    item.setBackground(
                        QColor(
                            self.theme_colors["green"]
                            if value == "PRESENT"
                            else self.theme_colors["red"]
                            if value == "ABSENT"
                            else self.theme_colors["amber"]
                        )
                    )
            combo = self.table.cellWidget(index, 4)
            if combo is None:
                combo = QComboBox()
                combo.addItems(["UNMARKED", "PRESENT", "ABSENT"])
                combo.currentTextChanged.connect(lambda mark, sid=row["student_id"]: self.mark(sid, mark))
                self.table.setCellWidget(index, 4, combo)
            if not combo.view().isVisible() and combo.currentText() != row["status"]:
                combo.blockSignals(True)
                combo.setCurrentText(row["status"])
                combo.blockSignals(False)
            combo.setEnabled(s["state"] != "APPROVED")
        counts = {
            status: sum(r["status"] == status for r in s["roster"]) for status in ("PRESENT", "ABSENT", "UNMARKED")
        }
        reviews = sum(bool(r["review"] and not r["review"]["resolved"]) for r in s["roster"])
        submissions = sum(bool(r["submission"]) for r in s["roster"])
        active = sum(r["enrollment_state"] == "ACTIVE" for r in s["roster"])
        left = max(0, int((parse_stamp(s["close_at"]) - self.runtime.now()).total_seconds()))
        self.summary.setText(
            f"{s['course']} · {s['section']}\n{s['state']} · {left}s collection remaining\n"
            f"Roster {len(s['roster'])} · Active biometrics {active}\n"
            f"Matched & submitted {submissions} · {'Final' if approved else 'Draft'} Present {counts['PRESENT']} "
            f"· Absent {counts['ABSENT']}\n"
            f"UNMARKED {counts['UNMARKED']} · Unresolved reviews {reviews}\n"
            f"Approved revision {s['revision']} · Unsynced events {len(self.runtime.pending_events())}"
        )

    def mark(self, sid, mark):
        self.editing = True
        try:
            reason, accepted = QInputDialog.getText(
                self, "Faculty attendance decision", "Reason / physical cross-check (required)"
            )
            if accepted:
                self.runtime.mark(self.selected_session, sid, mark, reason)
        except ValueError as exc:
            QMessageBox.warning(self, "Mark attendance", str(exc))
        finally:
            self.editing = False
            self.render_roster()

    def approve(self):
        if not self.selected_session:
            return
        self.editing = True
        try:
            s = self.runtime.session(self.selected_session)
            dialog = HeadcountReviewDialog(s, self.headcount.value(), self)
            dialog.exec()
            if dialog.action:
                self.headcount.setValue(dialog.headcount.value())
                self.runtime.record_headcount(self.selected_session, dialog.headcount.value())
            if dialog.action == "review":
                index = next(i for i, row in enumerate(s["roster"]) if row["student_id"] == dialog.review_student_id)
                self.table.selectRow(index)
                self.table.scrollToItem(self.table.item(index, 0))
                self.table.cellWidget(index, 4).setFocus()
                self.table.cellWidget(index, 4).showPopup()
                return
            if dialog.action != "approve":
                return
            discrepancy = dialog.reason.toPlainText().strip() if dialog.report["difference"] else ""
            self.runtime.approve(self.selected_session, dialog.headcount.value(), discrepancy)
            self.refresh_saved()
        except ValueError as exc:
            QMessageBox.warning(self, "Approval requires review", str(exc))
        finally:
            self.editing = False
            self.render_roster()

    def amend(self):
        index = self.table.currentRow()
        if index < 0 or not self.selected_session:
            return
        self.editing = True
        try:
            s = self.runtime.session(self.selected_session)
            row = s["roster"][index]
            status, accepted = QInputDialog.getItem(
                self, "Amend approved attendance", row["roll_number"], ["PRESENT", "ABSENT"], editable=False
            )
            if not accepted:
                return
            reason, accepted = QInputDialog.getText(self, "Audited amendment", "Required correction reason")
            if not accepted:
                return
            self.runtime.amend(s["id"], row["student_id"], status, reason, self.headcount.value(), reason)
            self.refresh_saved()
        except ValueError as exc:
            QMessageBox.warning(self, "Amendment", str(exc))
        finally:
            self.editing = False
            self.render_roster()

    def probe_hotspot(self):
        self.task(
            lambda: self.hotspot.status(), lambda value: self.network_status.setText("Windows Mobile Hotspot: " + value)
        )

    def start_hotspot(self):
        try:
            self.runtime._require()
            ssid, password = self.ssid.text(), self.wifi_password.text()
            self.task(
                lambda: self.hotspot.start(ssid, password),
                lambda _: self.network_status.setText(
                    "Application-managed hotspot started. Verify the address and trusted HTTPS before student intake."
                ),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Faculty authorization", str(exc))

    def create_certificates(self):
        directory, address = Path(self.cert_dir.text()), self.hotspot_ip.text()
        self.task(
            lambda: create_tls_material(directory, address),
            lambda result: self.network_status.setText(
                "Install and trust this public CA on consenting demo phones: "
                + str(result["ca"])
                + ". The CA was not installed automatically."
            ),
        )

    def start_listener(self, diagnostic_only=False):
        try:
            self.runtime._require()
            if self._after_hours() and not self._override_allowed():
                raise ValueError("authorized after-hours override is required")
            certs = Path(self.cert_dir.text())
            address = self.hotspot_ip.text()
            trusted = self.trusted.isChecked()
            self.save_network_config()
            self.task(
                lambda: self.listener.start(
                    address,
                    9443,
                    certs / "classroom-server.pem",
                    certs / "classroom-server.key",
                    phone_trust_verified=trusted,
                    static_dir=self.static_dir,
                    models_dir=self.models_dir,
                    diagnostic_only=diagnostic_only,
                ),
                lambda _: self.network_status.setText(
                    f"{'Camera diagnostic (no intake)' if diagnostic_only else 'Student listener'} active only on "
                    f"https://{address}:9443. Verify phone trust and camera operation on each demo phone."
                ),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Student intake blocked", str(exc))

    def save_network_config(self):
        time.fromisoformat(self.closing.text())
        self.runtime.store.kv_set(
            "network",
            {
                "ssid": self.ssid.text(),
                "address": self.hotspot_ip.text(),
                "cert_dir": self.cert_dir.text(),
                "closing": self.closing.text(),
            },
        )

    def wifi_qr(self):
        def escape(value):
            for char in ("\\", ";", ",", ":", '"'):
                value = value.replace(char, "\\" + char)
            return value

        self.connection_qr.setPixmap(
            qr_pixmap(f"WIFI:T:WPA;S:{escape(self.ssid.text())};P:{escape(self.wifi_password.text())};;")
        )

    def stop_network(self):
        self.prepared = None
        self.wifi_password.clear()
        if self.connection_dialog and self.connection_dialog.isVisible():
            self.connection_dialog.reject()
        future = self.network_cleanup.submit(lambda: self.classroom_flow().stop())
        future.add_done_callback(
            lambda done: self.bridge.network_stopped.emit(
                "Classroom stopped. Saved attendance remains available."
                if done.exception() is None
                else "Windows could not finish hotspot shutdown: " + str(done.exception())
            )
        )

    def lock_now(self, reason=None):
        with self.security_lock:
            self.security_epoch += 1
            self.runtime.privacy_lock()
        self.stop_network()
        self.listener.stop()
        for dialog in (self.connection_dialog, self.start_dialog):
            if dialog and dialog.isVisible():
                dialog.reject()
        modal = QApplication.activeModalWidget()
        if modal and hasattr(modal, "reject"):
            modal.reject()
        self.tabs.setTabEnabled(1, False)
        self.table.setRowCount(0)
        self._roster_key = None
        self.qr.clear()
        self.connection_qr.clear()
        self.wifi_password.clear()
        self.password.clear()
        self.pin.clear()
        self.tabs.setCurrentIndex(0)
        message = reason if isinstance(reason, str) and reason else "Faculty UI locked."
        message += " Approved records and unsynced events are preserved."
        self.auth_status.setText(message)
        self.statusBar().showMessage(message)
        self._refresh_hours_notice()
        # Queue behind any in-flight network start; never leave a late hotspot/listener alive.
        self.pool.submit(lambda: self.classroom_flow().stop())

    def _local_now(self):
        snapshot = self.runtime.store.kv_get("snapshot", {})
        zone = ZoneInfo(snapshot.get("policy", {}).get("timezone", "Asia/Kolkata"))
        return self.runtime.now().replace(tzinfo=UTC).astimezone(zone)

    def _local_day(self):
        return str(self._local_now().date())

    def _override_allowed(self):
        return self.override.isChecked() and self.override_day == self._local_day()

    def _after_hours(self):
        try:
            return self._local_now().time().replace(tzinfo=None) >= time.fromisoformat(self.closing.text())
        except ValueError:
            return True

    def _refresh_hours_notice(self):
        if self.override.isChecked() and self.override_day != self._local_day():
            self.override.blockSignals(True)
            self.override.setChecked(False)
            self.override.blockSignals(False)
            self.override_day = None
        after, allowed = self._after_hours(), self._override_allowed()
        self.hours_notice.setVisible(after or allowed)
        self.override.setVisible(after or allowed)
        if allowed:
            text = "After-hours use is allowed for today. Your timetable's attendance windows still apply."
        else:
            text = (
                f"Automatic lock starts at {self.closing.text()}; it is now {self._local_now():%H:%M}. "
                "To sign in after hours, confirm that you are authorized to continue today. "
                "Your saved attendance is safe."
            )
        self.hours_notice.setText(text)

    def _allow_sign_in_hours(self):
        self._refresh_hours_notice()
        if not self._after_hours() or self._override_allowed():
            return True
        try:
            time.fromisoformat(self.closing.text())
        except ValueError:
            QMessageBox.warning(self, "Closing time", "Enter a valid closing time in Settings before signing in.")
            return False
        answer = QMessageBox.question(
            self,
            "Continue after hours today?",
            f"Automatic lock starts at {self.closing.text()}; it is now {self._local_now():%H:%M}.\n\n"
            "Are you authorized to continue after hours today? Choose Yes to sign in without "
            "being immediately locked again. Timetable windows still apply.\n"
            "Cancel keeps your entered details so you can return later.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.override.setChecked(True)
        return True

    def tick(self):
        self._refresh_hours_notice()
        if not self.runtime.unlocked:
            return
        try:
            snap = self.runtime._require()
            if self._after_hours() and not self._override_allowed():
                self.lock_now(
                    f"Automatically locked at {self.closing.text()}. "
                    "Sign in again and confirm authorized use after hours to continue today."
                )
                return
            expired = False
            for s in self.runtime.store.sessions():
                if s["state"] == "COLLECTING" and parse_stamp(s["close_at"]) <= self.runtime.now():
                    self.runtime.close_collection(s["id"])
                    expired = True
            if expired:
                self.stop_network()
                self.qr.setText("Five minutes finished. Review the roster and approve attendance.")
            if self.editing:
                return
            self.refresh_class_choices()
            if self.listener.server and int(datetime.now().timestamp()) % 5 == 0:
                if self.hotspot.status() != "ON":
                    self.classroom_flow().stop()
                    self.runtime.privacy_lock()
                    self.tabs.setTabEnabled(1, False)
                    self.network_status.setText("Hotspot disconnected; intake closed and faculty UI locked.")
                    return
            self.render_roster()
            if self.selected_session and self.listener.server and not self.listener.diagnostic_only:
                try:
                    qr = self.runtime.current_qr(self.selected_session)["token"]
                    if qr != self.last_qr:
                        self.qr.setPixmap(qr_pixmap(f"https://{self.hotspot_ip.text()}:9443/classroom#{qr}"))
                        self.last_qr = qr
                except ValueError:
                    self.qr.setText("Collection closed. Faculty can review and approve the saved roster.")
            self.remind(snap)
        except ValueError:
            self.lock_now()

    def remind(self, snap):
        local = self.runtime.now().replace(tzinfo=UTC).astimezone(ZoneInfo(snap["policy"]["timezone"]))
        day = str(local.date())
        if any(h["date"] == day for h in snap["holidays"]):
            return
        sent = self.runtime.store.kv_get("reminders", [])
        for t in snap["timetable"]:
            if t["weekday"] != local.weekday() or t["is_break"]:
                continue
            if any(
                c["date"] == day
                and c["section_id"] == t["section_id"]
                and c["course_id"] == t["course_id"]
                and c["period_number"] == t["period_number"]
                for c in snap.get("cancelled_classes", [])
            ):
                continue
            period = next((p for p in snap["periods"] if p["number"] == t["period_number"]), {})
            start = t.get("start_time") or period.get("start_time")
            end = t.get("end_time") or period.get("end_time")
            bounds = class_bounds(local, start, end)
            if bounds is None or period.get("is_break"):
                continue
            ends = bounds[1]
            seconds = (local.replace(tzinfo=None) - ends).total_seconds()
            key = f"{day}:{t['section_id']}:{t['course_id']}:{t['period_number']}"
            taken = any(
                s["date"] == day
                and s["section_id"] == t["section_id"]
                and s["course_id"] == t["course_id"]
                and s["period_number"] == t["period_number"]
                for s in self.runtime.store.sessions()
            )
            if 0 <= seconds <= START_GRACE_SECONDS and key not in sent and not taken:
                course = next((c["course"] for c in snap["classes"] if c["course_id"] == t["course_id"]), "class")
                cutoff = (ends + timedelta(seconds=START_GRACE_SECONDS)).strftime("%H:%M")
                self.tray.showMessage(
                    "AttendX attendance reminder",
                    f"{course} has ended and attendance has not been started. "
                    f"Start by {cutoff}; collection lasts five minutes.",
                )
                sent.append(key)
                self.runtime.store.kv_set("reminders", sent[-500:])

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "AttendX Faculty", "Running in the tray. Use Quit AttendX Faculty to stop the application."
        )

    def shutdown(self):
        self.timer.stop()
        self.sync_timer.stop()
        with self.security_lock:
            self.security_epoch += 1
            self.runtime.privacy_lock()
        self.listener.stop()
        self.phone_setup.stop()
        # Wait for bounded in-flight starts before the final ownership-aware cleanup.
        # No worker may reprovision or leave a late listener/hotspot behind after exit.
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.network_cleanup.shutdown(wait=True, cancel_futures=False)
        self.listener.stop()
        self.phone_setup.stop()
        try:
            self.hotspot.stop_owned()
        except Exception:
            log.warning("application-managed hotspot could not be stopped")
        if isinstance(self.runtime.engine, RealFaceEngine):
            self.runtime.engine.close()


def main():
    parser = argparse.ArgumentParser(description="AttendX faculty-only Windows desktop")
    parser.add_argument(
        "--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AttendXFaculty"
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "ATTENDX_FACULTY_MODELS",
                str(
                    Path(sys.executable).parent / "models" if getattr(sys, "frozen", False) else PROJECT_DIR / "models"
                ),
            )
        ),
    )
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-models", action="store_true")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=args.data_dir / "faculty.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    engine = RealFaceEngine(args.models_dir, args.device, verify_hashes=True)
    if args.check_models:
        import numpy as np

        from attendx.config import RUNTIME_DEFAULTS

        engine.warmup()
        observed = engine.observe(np.full((480, 640, 3), 128, np.uint8), RUNTIME_DEFAULTS)
        report = {"engine": engine.status(), "blank_frame_faces": observed.n_faces}
        if args.report:
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        engine.close()
        return 0
    application = QApplication(sys.argv[:1])
    application.setApplicationName("AttendX Faculty")
    application.setQuitOnLastWindowClosed(False)
    runtime = FacultyRuntime(args.data_dir, engine=engine)
    window = FacultyWindow(runtime, models_dir=args.models_dir, static_dir=resources() / "frontend" / "dist")
    window.show()
    if args.smoke_test:

        def done():
            if args.report:
                args.report.write_text(
                    json.dumps(
                        {
                            "window_title": window.windowTitle(),
                            "tabs": window.tabs.count(),
                            "locked": not runtime.unlocked,
                            "student_listener_started": bool(window.listener.server),
                            "model_files_external": True,
                            "qt_version": __import__("PySide6").__version__,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                window.grab().save(str(args.report.with_suffix(".png")))
            application.quit()

        QTimer.singleShot(1000, done)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
