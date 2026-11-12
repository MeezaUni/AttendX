"""Small classroom dialogs: one start action and QR codes that never crop."""

import secrets

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from attendx.faculty.theme import ReadableCheckBox


class QrLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:white;color:#17243b;border:1px solid #dce2ec;border-radius:12px;")

    def setPixmap(self, pixmap):
        self.source = QPixmap(pixmap)
        self._fit()

    def clear(self):
        self.source = None
        super().clear()

    def setText(self, text):
        self.source = None
        super().setText(text)

    def _fit(self):
        if self.source is not None:
            size = self.contentsRect().size()
            super().setPixmap(
                self.source.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class ConnectionDialog(QDialog):
    def __init__(self, owner, prepared, *, attendance=False, parent=None):
        super().__init__(parent or owner)
        self.owner, self.prepared = owner, dict(prepared)
        self.setWindowTitle("Classroom connection")
        available = owner.screen().availableGeometry()
        self.resize(min(650, available.width() - 40), min(720, available.height() - 70))
        self.setMinimumSize(380, 480)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        for title in ("1 · Join Wi-Fi", "Phone setup · once", "2 · Attendance"):
            page = QWidget()
            self.tabs.addTab(page, title)
        wifi = QVBoxLayout(self.tabs.widget(0))
        wifi.addWidget(QLabel("Scan this QR with the phone's camera to join the classroom Wi-Fi."))
        self.wifi = QrLabel()
        wifi.addWidget(self.wifi, 1)
        self.wifi.setPixmap(owner.make_qr(owner.wifi_payload(prepared["ssid"], prepared["password"]), 650))
        self.credentials = credentials = QLabel(f"Wi-Fi: {prepared['ssid']}\nPassword: {prepared['password']}")
        credentials.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        credentials.setStyleSheet("font-size:20px;font-weight:600;padding:12px;")
        wifi.addWidget(credentials)
        setup = QVBoxLayout(self.tabs.widget(1))
        text = QLabel(
            "First time on this phone? After joining Wi-Fi, scan below in Safari.\n"
            "Install the AttendX profile, enable trust in Settings, then check the camera.\n"
            "This is one-time phone setup for your AttendX deployment, not every class."
        )
        text.setWordWrap(True)
        setup.addWidget(text)
        code = QrLabel()
        code.setPixmap(owner.make_qr(f"http://{prepared['address']}:9442/", 650))
        setup.addWidget(code, 1)
        detail = QLabel(f"Phone setup: http://{prepared['address']}:9442/\nCA SHA-256: {prepared['fingerprint']}")
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        setup.addWidget(detail)
        room = QVBoxLayout(self.tabs.widget(2))
        self.attendance_note = QLabel("Start attendance after the phones are ready.")
        self.attendance_note.setWordWrap(True)
        room.addWidget(self.attendance_note)
        self.attendance_qr = QrLabel()
        room.addWidget(self.attendance_qr, 1)
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        layout.addWidget(done)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.finished.connect(self.finished_display)
        if attendance:
            self.tabs.setCurrentIndex(2)
        self.refresh()

    def finished_display(self, result):
        self.timer.stop()
        self.wifi.clear()
        self.attendance_qr.clear()
        self.credentials.clear()
        self.prepared["password"] = ""

    def refresh(self):
        try:
            session = self.owner.runtime.session(self.owner.selected_session)
            token = self.owner.runtime.current_qr(session["id"])["token"]
            self.attendance_qr.setPixmap(
                self.owner.make_qr(f"https://{self.prepared['address']}:9443/classroom#{token}", 700)
            )
            from attendx.faculty.runtime import parse_stamp

            seconds = max(0, int((parse_stamp(session["close_at"]) - self.owner.runtime.now()).total_seconds()))
            self.attendance_note.setText(
                f"{session['course']} · {session['section']} · {seconds // 60}:{seconds % 60:02d} remaining\n"
                "Scan to begin. After the face check, scan a fresh code again."
            )
        except (ValueError, TypeError, KeyError):
            self.attendance_qr.clear()
            self.attendance_note.setText("Attendance collection is not running. The faculty roster remains available.")


class StartDialog(QDialog):
    def __init__(self, owner, meeting):
        super().__init__(owner)
        self.owner, self.meeting, self.prepared = owner, meeting, None
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.cancelled = False
        self.setWindowTitle("Start classroom attendance")
        self.resize(560, 350)
        layout = QVBoxLayout(self)
        heading = QLabel(
            f"{meeting['course']} · {meeting['section']}\nPeriod {meeting['period_number']} · "
            f"{meeting['start_time'][:5]}–{meeting['end_time'][:5]}"
        )
        heading.setStyleSheet("font-size:22px;font-weight:600;")
        layout.addWidget(heading)
        self.status = QLabel("Checking Windows hotspot support…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.connections = QPushButton("Show Wi-Fi QR and phone setup")
        self.connections.setVisible(False)
        self.connections.clicked.connect(lambda: owner.show_connection(prepared=self.prepared))
        layout.addWidget(self.connections)
        self.confirm = ReadableCheckBox("Phones have trusted the AttendX certificate and their camera check works")
        self.confirm.setVisible(False)
        self.confirm.toggled.connect(lambda checked: self.primary.setEnabled(checked))
        layout.addWidget(self.confirm)
        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.primary = QPushButton("Start")
        self.primary.setObjectName("primary")
        self.primary.setEnabled(False)
        self.primary.clicked.connect(self.start)
        actions.addWidget(self.primary)
        layout.addLayout(actions)
        self.finished.connect(self.finished_setup)
        owner.task(lambda: owner.hotspot.status(), self.probed)

    def probed(self, status):
        if not self.cancelled:
            self.status.setText(
                "Ready. Start prepares classroom Wi-Fi and secure phone access automatically.\n"
                "The five-minute timer starts only when setup is ready."
            )
            self.primary.setEnabled(True)

    def failed(self, message):
        self.prepared = self.owner.prepared = None
        self.status.setText(message)
        self.confirm.setChecked(False)
        self.connections.setVisible(False)
        self.confirm.setVisible(False)
        self.primary.setText("Retry Start")
        self.primary.setEnabled(True)

    def alive(self):
        return not self.cancelled and self.owner.runtime.unlocked and self.owner.security_epoch == self.epoch

    def start(self):
        self.epoch = self.owner.security_epoch
        self.primary.setEnabled(False)
        self.status.setText("Preparing classroom…")
        if self.prepared:
            self.begin()
            return
        ssid = self.owner.ssid.text().strip() or "AttendX-Classroom"
        password = self.owner.wifi_password.text() or secrets.token_urlsafe(12)
        self.owner.task(lambda: self.owner.classroom_flow().prepare(ssid, password, alive=self.alive), self.ready)

    def ready(self, prepared):
        if self.cancelled:
            return
        self.prepared = self.owner.prepared = prepared
        self.owner.wifi_password.setText(prepared["password"])
        self.owner.hotspot_ip.setText(prepared["address"])
        self.owner.cert_dir.setText(prepared["cert_dir"])
        if prepared["phone_ready"]:
            self.begin()
        else:
            self.status.setText(
                "Laptop ready. Join the Wi-Fi and complete one-time phone setup.\n"
                "The attendance timer has not started yet. New phones need this setup too."
            )
            self.connections.setVisible(True)
            self.confirm.setVisible(True)
            self.primary.setText("Start five-minute attendance")

    def begin(self):
        phone_confirmed = self.confirm.isChecked()
        self.owner.task(
            lambda: self.owner.classroom_flow().begin(
                self.meeting, self.prepared, phone_confirmed=phone_confirmed, alive=self.alive
            ),
            self.started,
        )

    def started(self, session):
        if self.cancelled:
            return
        self.owner.selected_session = session["id"]
        self.owner.refresh_saved()
        self.accept()
        self.owner.show_connection(attendance=True)

    def finished_setup(self, result):
        if result != QDialog.DialogCode.Accepted:
            self.cancelled = True
            self.owner.stop_network()
