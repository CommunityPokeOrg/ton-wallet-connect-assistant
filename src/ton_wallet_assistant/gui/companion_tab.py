"""Mobile companion tab: start/stop the LAN bridge, show the pairing URL/QR,
and approve or reject payloads relayed from the phone."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..companion import PairingManager
from ..companion.protocol import PayloadKind, RequestState, TransferDetails
from ..qr import qr_png_bytes
from ..session import WalletSession
from ..wallet.keystore import WrongPasswordError
from .async_loop import AsyncLoop
from .dialogs import RequestApprovalDialog, show_error, show_info


class CompanionTab(QWidget):
    def __init__(self, session: WalletSession, async_loop: AsyncLoop) -> None:
        super().__init__()
        self.session = session
        self.async_loop = async_loop
        self.manager = PairingManager(
            host="127.0.0.1" if session.demo else "0.0.0.0",
            demo=session.demo,
            network=session.account.network,
        )
        self.manager.transfer_handler = self._execute_transfer
        self.manager.connect_handler = self._execute_connect
        self._pending_words: list[str] | None = None
        self._seen_ids: set[str] = set()
        self._dialog_open_for: str | None = None

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.toggle_btn = QPushButton("Start mobile pairing")
        self.toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self.toggle_btn)
        self.state_label = QLabel("Bridge stopped")
        header.addWidget(self.state_label, 1)
        layout.addLayout(header)

        if session.demo:
            flag = QLabel("DEMO MODE — the bridge binds to localhost and simulated requests only.")
            flag.setStyleSheet("color:#f0a020; font-weight:bold;")
            flag.setWordWrap(True)
            layout.addWidget(flag)

        self.url_edit = QLineEdit()
        self.url_edit.setReadOnly(True)
        self.url_edit.setPlaceholderText("Pairing URL appears here after starting the bridge")
        layout.addWidget(self.url_edit)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.qr_label)

        hint = QLabel(
            "Scan the pairing QR (or open the URL) on your phone, then use the "
            "mobile page to scan TonConnect / ton:// QR codes. Each scanned "
            "payload arrives here for explicit approval — nothing is signed "
            "or forwarded automatically."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9AA6B2;")
        layout.addWidget(hint)

        form = QFormLayout()
        self.pending_label = QLabel("0")
        form.addRow("Pending requests", self.pending_label)
        layout.addLayout(form)

        self.request_list = QListWidget()
        self.request_list.itemClicked.connect(self._open_request)
        layout.addWidget(self.request_list, 1)

        self.poll = QTimer(self)
        self.poll.setInterval(1000)
        self.poll.timeout.connect(self._refresh_requests)
        self.poll.start()

    # ----------------------------------------------------------- lifecycle

    def _toggle(self) -> None:
        if self.manager.running:
            self.async_loop.submit(self.manager.stop(), self._on_stopped)
            self.state_label.setText("Stopping…")
            self.toggle_btn.setEnabled(False)
        else:
            self.async_loop.submit(self.manager.start(), self._on_started)
            self.state_label.setText("Starting…")
            self.toggle_btn.setEnabled(False)

    def _on_started(self, url: str | None, error) -> None:
        self.toggle_btn.setEnabled(True)
        if error:
            self.state_label.setText("Bridge failed to start")
            show_error(self, "Pairing failed", str(error))
            return
        self.state_label.setText("Bridge running — pair your phone")
        self.toggle_btn.setText("Stop pairing")
        self.url_edit.setText(self.manager.pairing_url)
        pixmap = QPixmap()
        pixmap.loadFromData(qr_png_bytes(self.manager.pairing_url, box_size=6))
        self.qr_label.setPixmap(
            pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio)
        )

    def _on_stopped(self, _result, error) -> None:
        self.toggle_btn.setEnabled(True)
        if error:
            show_error(self, "Stop failed", str(error))
        self.state_label.setText("Bridge stopped")
        self.toggle_btn.setText("Start mobile pairing")
        self.url_edit.clear()
        self.qr_label.clear()

    # ------------------------------------------------------------ requests

    def _refresh_requests(self) -> None:
        pending = self.manager.pending_requests()
        self.pending_label.setText(str(len(pending)))
        self.request_list.clear()
        for req in self.manager.all_requests():
            item = QListWidgetItem(self._describe(req))
            item.setData(Qt.ItemDataRole.UserRole, req.request_id)
            if req.state is not RequestState.PENDING:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.request_list.addItem(item)
        # Auto-open the approval dialog for a newly-arrived pending request.
        for req in pending:
            if req.request_id not in self._seen_ids:
                self._seen_ids.add(req.request_id)
                if self._dialog_open_for is None:
                    self._open_request_id(req.request_id)
                break

    @staticmethod
    def _describe(req) -> str:
        if req.kind is PayloadKind.TON_TRANSFER:
            d: TransferDetails = req.payload
            label = f"Send {d.amount_text} → {d.address[:14]}…"
        else:
            label = f"TonConnect link ({req.payload.wallet_host})"
        return f"[{req.state.value}] {label} — from {req.origin_ip}"

    def _open_request(self, item: QListWidgetItem) -> None:
        req_id = item.data(Qt.ItemDataRole.UserRole)
        self._open_request_id(req_id)

    def _open_request_id(self, req_id: str) -> None:
        req = self.manager.get(req_id)
        if req is None or req.state is not RequestState.PENDING:
            return
        self._dialog_open_for = req_id
        dialog = RequestApprovalDialog(
            self, req, demo=self.session.demo, network=self.session.account.network
        )
        if dialog.exec() == RequestApprovalDialog.DialogCode.Accepted:
            self._approve(req_id, dialog.password)
        else:
            self.manager.reject(req_id)
        self._dialog_open_for = None
        self._refresh_requests()

    # ------------------------------------------------------------ handlers

    def _approve(self, req_id: str, password: str) -> None:
        req = self.manager.get(req_id)
        if req is None:
            return
        if req.kind is PayloadKind.TON_TRANSFER and not self.session.demo:
            if not password:
                show_error(self, "Password required", "Enter the wallet password to sign.")
                return
            try:
                self._pending_words = self.session.unlock(password)
            except WrongPasswordError:
                show_error(self, "Incorrect password", "The wallet password is incorrect.")
                return
        else:
            self._pending_words = []
        self.async_loop.submit(self.manager.approve(req_id), self._on_approved)

    def _on_approved(self, result: str | None, error) -> None:
        self._pending_words = None
        if error:
            show_error(self, "Request failed", str(error))
        else:
            show_info(self, "Request completed", result or "Done")
        self._refresh_requests()

    async def _execute_transfer(self, req) -> str:
        d: TransferDetails = req.payload
        words = self._pending_words or []
        if not self.session.demo and not words:
            raise RuntimeError("wallet is locked")
        if d.jetton:
            jettons = await self.session.chain.get_jettons(self.session.account.friendly_bounceable)
            match = next((j for j in jettons if j.address == d.jetton), None)
            if match is None:
                raise RuntimeError("no jetton balance for the requested asset")
            if d.amount_nano is None:
                raise RuntimeError("link does not specify an amount")
            return await self.session.chain.send_jetton(
                words, self.session.account.wallet_version, match, d.address, d.amount_nano, d.comment
            )
        if d.amount_nano is None:
            raise RuntimeError("link does not specify an amount")
        return await self.session.chain.send(
            words, self.session.account.wallet_version, d.address, d.amount_nano, d.comment
        )

    async def _execute_connect(self, req) -> str:
        d = req.payload
        if self.session.demo:
            return f"demo: universal link for {d.wallet_host} accepted (not opened)"
        import webbrowser

        webbrowser.open(d.url)
        return f"forwarded universal link to wallet app ({d.wallet_host})"

    # ---------------------------------------------------------------- close

    def shutdown(self) -> None:
        self.poll.stop()
        if self.manager.running:
            self.async_loop.submit(self.manager.stop())
