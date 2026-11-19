"""Explicit faculty reconciliation, with a recount before final approval."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from attendx.faculty.reconciliation import headcount_report


class HeadcountReviewDialog(QDialog):
    def __init__(self, session, count, parent, mark=None):
        super().__init__(parent)
        self.session, self.action, self.review_student_id = session, None, None
        # mark(student_id, status, reason) -> updated session; decisions are made right here.
        self.mark = mark
        self.setWindowTitle("Cross-check attendance and headcount")
        available = parent.screen().availableGeometry()
        self.resize(min(760, available.width() - 40), min(650, available.height() - 60))
        layout = QVBoxLayout(self)
        title = QLabel(f"{session['course']} · {session['section']}\nReview draft decisions before final approval")
        title.setStyleSheet("font-size:20px;font-weight:600;")
        layout.addWidget(title)
        form = QFormLayout()
        self.headcount = QSpinBox()
        self.headcount.setRange(0, 10000)
        self.headcount.setValue(count)
        form.addRow("Physical headcount — you can recount and change this", self.headcount)
        layout.addLayout(form)
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)
        self.candidates = QListWidget()
        self.candidates.setWordWrap(True)
        self.candidates.setMinimumHeight(120)
        self.candidates.itemDoubleClicked.connect(lambda _: self.review_selected())
        layout.addWidget(self.candidates, 1)
        quick = QHBoxLayout()
        self.present_button = QPushButton("Mark selected Present")
        self.present_button.clicked.connect(lambda: self.mark_selected("PRESENT"))
        self.absent_button = QPushButton("Mark selected Absent")
        self.absent_button.clicked.connect(lambda: self.mark_selected("ABSENT"))
        self.all_absent_button = QPushButton("Mark all unmarked Absent")
        self.all_absent_button.clicked.connect(self.mark_unmarked_absent)
        for button in (self.present_button, self.absent_button, self.all_absent_button):
            button.setAutoDefault(False)
            button.setVisible(mark is not None)
            quick.addWidget(button)
        layout.addLayout(quick)
        self.reason_label = QLabel("If the discrepancy remains after cross-checking, explain it before approving:")
        self.reason_label.setWordWrap(True)
        layout.addWidget(self.reason_label)
        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText("Required only if physical headcount and Present marks differ")
        self.reason.setMaximumHeight(76)
        layout.addWidget(self.reason)
        buttons = QHBoxLayout()
        self.review_button = QPushButton("Review selected student")
        self.review_button.clicked.connect(self.review_selected)
        buttons.addWidget(self.review_button)
        back = QPushButton("Save count & return")
        back.clicked.connect(self.back)
        buttons.addWidget(back)
        self.approve_button = QPushButton("Approve final attendance")
        self.approve_button.setObjectName("primary")
        self.approve_button.clicked.connect(self.approve)
        buttons.addWidget(self.approve_button)
        for button in (back, self.review_button, self.approve_button):
            button.setAutoDefault(False)
        layout.addLayout(buttons)
        self.headcount.valueChanged.connect(self.refresh)
        self.reason.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.report = report = headcount_report(self.session, self.headcount.value())
        delta = report["difference"]
        text = (
            f"Physical headcount {report['headcount']} · Draft Present {report['present']} "
            f"· Matched submissions {report['matched']}.\n"
        )
        if delta > 0:
            text += (
                f"You counted {delta} more people than Present marks. "
                "Cross-check missing submissions, failed checks and absence decisions."
            )
        elif delta < 0:
            text += f"There are {-delta} more Present marks than people counted. Cross-check Present rows or recount."
        else:
            text += "The counts agree. Cross-check any remaining unmarked or unresolved students."
        if report["unmarked"]:
            text += f"\n{report['unmarked']} students still need an explicit faculty decision."
        text += "\nHeadcount alone cannot identify a missing or extra person. Final approval freezes this roster."
        self.explanation.setText(text)
        selected = self.candidates.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.candidates.clear()
        for row in report["candidates"]:
            item = QListWidgetItem(
                f"{row['roll_number']} · {row['name']} · {row['status']}\n{row['verification']}\n{row['check_reason']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, row["student_id"])
            self.candidates.addItem(item)
            if selected_id == row["student_id"]:
                self.candidates.setCurrentItem(item)
        if self.candidates.count() and not self.candidates.currentItem():
            self.candidates.setCurrentRow(0)
        self.review_button.setEnabled(bool(report["candidates"]))
        editable = self.mark is not None and self.session["state"] != "APPROVED"
        self.present_button.setEnabled(editable and bool(report["candidates"]))
        self.absent_button.setEnabled(editable and bool(report["candidates"]))
        self.all_absent_button.setEnabled(editable and report["unmarked"] > 0)
        self.all_absent_button.setText(
            f"Mark all {report['unmarked']} unmarked Absent" if report["unmarked"] else "No unmarked students"
        )
        self.reason.setVisible(delta != 0)
        self.reason_label.setVisible(delta != 0)
        self.approve_button.setEnabled(
            report["can_approve"] and (delta == 0 or len(self.reason.toPlainText().strip()) >= 3)
        )

    def _reason(self, title, default):
        text, ok = QInputDialog.getText(self, title, "Reason / physical cross-check (required)", text=default)
        return text.strip() if ok else None

    def _apply(self, changes, reason):
        try:
            for student_id, status in changes:
                self.session = self.mark(student_id, status, reason)
        except ValueError as exc:
            QMessageBox.warning(self, "Mark attendance", str(exc))
        self.refresh()

    def mark_selected(self, status):
        item = self.candidates.currentItem()
        if not item or self.mark is None:
            return
        default = "Verified present in class" if status == "PRESENT" else "Not present in class"
        reason = self._reason(f"Mark {status.title()}", default)
        if reason is not None:
            self._apply([(item.data(Qt.ItemDataRole.UserRole), status)], reason)

    def mark_unmarked_absent(self):
        if self.mark is None:
            return
        unmarked = [r["student_id"] for r in self.session["roster"] if r["status"] == "UNMARKED"]
        if not unmarked:
            return
        reason = self._reason(f"Mark {len(unmarked)} unmarked students Absent", "Not present at headcount")
        if reason is not None:
            self._apply([(sid, "ABSENT") for sid in unmarked], reason)

    def review_selected(self):
        item = self.candidates.currentItem()
        if item:
            self.review_student_id = item.data(Qt.ItemDataRole.UserRole)
            self.action = "review"
            self.reject()

    def back(self):
        self.action = "back"
        self.reject()

    def approve(self):
        if self.approve_button.isEnabled():
            self.action = "approve"
            self.accept()
