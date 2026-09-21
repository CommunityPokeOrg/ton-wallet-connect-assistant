"""Onboarding screens: create / import / unlock / demo."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..wallet import DEFAULT_VERSION, SUPPORTED_VERSIONS, generate_mnemonic, parse_mnemonic_text, validate_mnemonic
from ..wallet.keystore import Keystore


class OnboardingWidget(QWidget):
    """Guides the user to an unlocked wallet or a demo session.

    Signals:
        wallet_created(words, password, version): create a new keystore
        wallet_imported(words, password, version): create keystore from an
            existing mnemonic
        keystore_unlocked(password): unlock the existing keystore
        demo_requested(): start an in-memory demo session
    """

    wallet_created = Signal(list, str, str)
    wallet_imported = Signal(list, str, str)
    keystore_unlocked = Signal(str)
    demo_requested = Signal()

    def __init__(self, keystore: Keystore, allow_demo: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.keystore = keystore
        self._pending_words: list[str] = []
        self._import_mode = False
        self._allow_demo = allow_demo

        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        header = QLabel("<h2>TON Wallet</h2>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        layout.addWidget(self.stack, 1)

        self.stack.addWidget(self._welcome_page())
        self.stack.addWidget(self._create_backup_page())
        self.stack.addWidget(self._create_password_page(import_mode=False))
        self.stack.addWidget(self._import_page())
        self.stack.addWidget(self._unlock_page())
        self.stack.setCurrentIndex(self.PAGE_UNLOCK if keystore.exists else self.PAGE_WELCOME)

    PAGE_WELCOME = 0
    PAGE_BACKUP = 1
    PAGE_PASSWORD = 2
    PAGE_IMPORT = 3
    PAGE_UNLOCK = 4

    # -------------------------------------------------------------- pages

    def _page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(f"<b>{title}</b>")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return page, layout

    def _demo_row(self, layout: QVBoxLayout) -> None:
        if not self._allow_demo:
            return
        row = QHBoxLayout()
        row.addStretch(1)
        demo = QPushButton("Try demo mode (fake wallet, no real funds)")
        demo.clicked.connect(self.demo_requested.emit)
        row.addWidget(demo)
        row.addStretch(1)
        layout.addLayout(row)

    def _welcome_page(self) -> QWidget:
        page, layout = self._page("Create or import a wallet")
        note = QLabel(
            "A 24-word recovery phrase controls the wallet. It is stored only\n"
            "on this machine, encrypted with your password."
        )
        layout.addWidget(note, alignment=Qt.AlignmentFlag.AlignCenter)
        create_btn = QPushButton("Create new wallet")
        create_btn.clicked.connect(self._start_create)
        import_btn = QPushButton("Import existing wallet")
        import_btn.clicked.connect(lambda: self.stack.setCurrentIndex(self.PAGE_IMPORT))
        layout.addWidget(create_btn)
        layout.addWidget(import_btn)
        layout.addWidget(QLabel("Wallet version:"), alignment=Qt.AlignmentFlag.AlignCenter)
        self.version_combo = QComboBox()
        self.version_combo.addItems(list(SUPPORTED_VERSIONS))
        self.version_combo.setCurrentText(DEFAULT_VERSION)
        layout.addWidget(self.version_combo, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        self._demo_row(layout)
        return page

    def _start_create(self) -> None:
        self._pending_words = generate_mnemonic()
        grid = self._backup_grid
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, word in enumerate(self._pending_words):
            grid.addWidget(QLabel(f"{i + 1}. {word}"), i // 4, i % 4)
        self.stack.setCurrentIndex(self.PAGE_BACKUP)

    def _create_backup_page(self) -> QWidget:
        page, layout = self._page("Back up your recovery phrase")
        warn = QLabel("Write these 24 words down and keep them safe. They are shown once.")
        warn.setWordWrap(True)
        layout.addWidget(warn)
        holder = QWidget()
        self._backup_grid = QGridLayout(holder)
        layout.addWidget(holder)
        self.backup_check = QCheckBox("I have written down my recovery phrase")
        layout.addWidget(self.backup_check)
        next_btn = QPushButton("Continue")
        next_btn.clicked.connect(self._backup_done)
        layout.addWidget(next_btn)
        back = QPushButton("Back")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(self.PAGE_WELCOME))
        layout.addWidget(back)
        return page

    def _create_password_page(self, import_mode: bool) -> QWidget:
        page, layout = self._page("Set a password")
        form = QFormLayout()
        self.pw1 = QLineEdit()
        self.pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password (min 8 chars)", self.pw1)
        form.addRow("Repeat password", self.pw2)
        layout.addLayout(form)
        self.create_error = QLabel("")
        self.create_error.setStyleSheet("color:#e74c3c;")
        layout.addWidget(self.create_error)
        self.pw_done = QPushButton("Set password & continue")
        self.pw_done.clicked.connect(self._finish_create)
        layout.addWidget(self.pw_done)
        back = QPushButton("Back")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(self.PAGE_WELCOME))
        layout.addWidget(back)
        return page

    def _backup_done(self) -> None:
        if not self.backup_check.isChecked():
            return
        self._import_mode = False
        self.stack.setCurrentIndex(self.PAGE_PASSWORD)
    def _import_page(self) -> QWidget:
        page, layout = self._page("Import an existing wallet")
        layout.addWidget(QLabel("Paste your 24-word recovery phrase:"))
        self.import_edit = QPlainTextEdit()
        self.import_edit.setPlaceholderText("word1 word2 … word24")
        self.import_edit.setFixedHeight(90)
        layout.addWidget(self.import_edit)
        self.import_error = QLabel("")
        self.import_error.setStyleSheet("color:#e74c3c;")
        layout.addWidget(self.import_error)
        go = QPushButton("Continue")
        go.clicked.connect(self._finish_import)
        layout.addWidget(go)
        back = QPushButton("Back")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(self.PAGE_WELCOME))
        layout.addWidget(back)
        self._demo_row(layout)
        return page

    def _unlock_page(self) -> QWidget:
        page, layout = self._page("Unlock your wallet")
        meta = self.keystore.meta() if self.keystore.exists else None
        if meta and meta.address_hint:
            layout.addWidget(QLabel(meta.address_hint), alignment=Qt.AlignmentFlag.AlignCenter)
        self.unlock_edit = QLineEdit()
        self.unlock_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.unlock_edit.setPlaceholderText("Password")
        self.unlock_edit.returnPressed.connect(self._finish_unlock)
        layout.addWidget(self.unlock_edit)
        self.unlock_error = QLabel("")
        self.unlock_error.setStyleSheet("color:#e74c3c;")
        layout.addWidget(self.unlock_error)
        btn = QPushButton("Unlock")
        btn.clicked.connect(self._finish_unlock)
        layout.addWidget(btn)
        layout.addStretch(1)
        self._demo_row(layout)
        return page

    # ------------------------------------------------------------- finish

    def _finish_create(self) -> None:
        if self.pw1.text() != self.pw2.text():
            self.create_error.setText("Passwords do not match")
            return
        if len(self.pw1.text()) < 8:
            self.create_error.setText("Password must be at least 8 characters")
            return
        words, self._pending_words = self._pending_words, []
        if self._import_mode:
            self.wallet_imported.emit(words, self.pw1.text(), self.version_combo.currentText())
        else:
            self.wallet_created.emit(words, self.pw1.text(), self.version_combo.currentText())

    def _finish_import(self) -> None:
        words = parse_mnemonic_text(self.import_edit.toPlainText())
        try:
            words = validate_mnemonic(words)
        except ValueError as exc:
            self.import_error.setText(str(exc))
            return
        self._pending_words = words
        self._import_mode = True
        self.stack.setCurrentIndex(self.PAGE_PASSWORD)

    def _finish_unlock(self) -> None:
        self.keystore_unlocked.emit(self.unlock_edit.text())
