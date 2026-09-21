"""Main window: onboarding gate -> sidebar-navigated wallet UI."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from ..config import AppConfig
from ..services.base import WalletService
from ..session import WalletSession, keystore_path
from ..wallet import DemoChainClient, TonApiClient, derive_account, generate_mnemonic
from ..wallet.account import WalletAccount
from ..wallet.keystore import Keystore, WrongPasswordError
from .async_loop import AsyncLoop
from .collectibles_tab import CollectiblesTab
from .companion_tab import CompanionTab
from .connect_tab import ConnectTab
from .dialogs import show_error
from .history_tab import HistoryTab
from .onboarding import OnboardingWidget
from .settings_tab import SettingsTab
from .telegram_tab import TelegramTab
from .wallet_tab import WalletTab


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, connect_service: WalletService) -> None:
        super().__init__()
        self.config = config
        self.connect_service = connect_service
        self.async_loop = AsyncLoop(self)
        self.session: WalletSession | None = None
        self.keystore = Keystore(keystore_path(config, config.network))

        self.setWindowTitle("TON Wallet")
        self.resize(820, 680)

        if config.demo_mode:
            self._start_demo()
        else:
            self._show_onboarding()

    # ------------------------------------------------------------- sessions

    def _show_onboarding(self) -> None:
        self.onboarding = OnboardingWidget(self.keystore)
        self.onboarding.wallet_created.connect(self._on_wallet_created)
        self.onboarding.wallet_imported.connect(self._on_wallet_created)
        self.onboarding.keystore_unlocked.connect(self._on_unlock)
        self.onboarding.demo_requested.connect(self._start_demo)
        self.setCentralWidget(self.onboarding)

    def _start_demo(self) -> None:
        async def build():
            words = generate_mnemonic()
            account = await derive_account(words, network=self.config.demo_network)
            return account

        self.async_loop.submit(build(), self._on_demo_account)

    def _on_demo_account(self, account: WalletAccount | None, error) -> None:
        if error:
            show_error(self, "Demo failed", str(error))
            return
        self._open_session(
            WalletSession(
                account=account,
                chain=DemoChainClient(self.config.demo_network),
                keystore=None,
                demo=True,
                connect_service=self.connect_service,
            )
        )

    def _on_wallet_created(self, words: list[str], password: str, version: str) -> None:
        async def setup():
            account = await derive_account(words, network=self.config.network, wallet_version=version)
            self.keystore.create(
                words,
                password,
                wallet_version=version,
                network=self.config.network,
                address_hint=account.friendly_bounceable,
            )
            return account

        self.async_loop.submit(setup(), self._on_account_ready)

    def _on_unlock(self, password: str) -> None:
        try:
            words = self.keystore.unlock(password)
        except WrongPasswordError:
            self.onboarding.unlock_error.setText("Incorrect password")
            return
        meta = self.keystore.meta()

        async def setup():
            return await derive_account(words, network=meta.network, wallet_version=meta.wallet_version)

        self.async_loop.submit(setup(), self._on_account_ready)

    def _on_account_ready(self, account: WalletAccount | None, error) -> None:
        if error:
            show_error(self, "Wallet error", str(error))
            return
        self._open_session(
            WalletSession(
                account=account,
                chain=TonApiClient(account.network, api_key=os.environ.get("TONAPI_KEY")),
                keystore=self.keystore,
                demo=False,
                connect_service=self.connect_service,
            )
        )

    def _open_session(self, session: WalletSession) -> None:
        self.session = session

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("sidebar")
        self.nav.setFixedWidth(180)
        for label in (
            "Wallet", "History", "Collectibles", "TonConnect", "Pairing", "Telegram", "Settings"
        ):
            self.nav.addItem(label)
        nav = self.nav

        self.pages = QStackedWidget()
        pages = self.pages
        self.wallet_tab = WalletTab(session, self.async_loop)
        self.history_tab = HistoryTab(session, self.async_loop)
        self.collectibles_tab = CollectiblesTab(session, self.async_loop)
        self.connect_tab = ConnectTab(self.config, self.connect_service, self.async_loop)
        self.companion_tab = CompanionTab(session, self.async_loop)
        self.telegram_tab = TelegramTab(session, self.async_loop)
        self.settings_tab = SettingsTab(self.config, session, self.async_loop, self._on_wallet_deleted)
        for page in (
            self.wallet_tab,
            self.history_tab,
            self.collectibles_tab,
            self.connect_tab,
            self.companion_tab,
            self.telegram_tab,
            self.settings_tab,
        ):
            pages.addWidget(page)

        nav.currentRowChanged.connect(pages.setCurrentIndex)
        nav.setCurrentRow(0)

        layout.addWidget(nav)
        layout.addWidget(pages, 1)
        self.setCentralWidget(root)
        suffix = " [DEMO]" if session.demo else ""
        self.setWindowTitle(f"TON Wallet — {session.account.short_address}{suffix}")

    def _on_wallet_deleted(self) -> None:
        self.session = None
        self._show_onboarding()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        try:
            if self.session is not None:
                self.companion_tab.shutdown()
                self.telegram_tab.shutdown()
                self.async_loop.submit(self.session.chain.close())
            self.async_loop.submit(self.connect_service.close())
        finally:
            self.async_loop.stop()
        super().closeEvent(event)
