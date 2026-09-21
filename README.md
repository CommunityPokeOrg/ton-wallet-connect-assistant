# TON Wallet Connect Assistant

A polished desktop application (Python + PySide6/Qt) that helps users connect
and manage a **TON wallet** through the [TonConnect](https://docs.tonconnect.org/)
protocol — the connection flow used by Telegram's built-in **Wallet**,
Tonkeeper, Tonhub, and other TON wallets.

## Features

- **Wallet picker** — the live TonConnect wallet registry (Telegram Wallet,
  Tonkeeper, Tonhub, …) filtered to wallets that work on desktop.
- **QR code + universal link** — scan with a phone wallet (e.g. the Wallet bot
  inside Telegram) or open the deep link on the same machine.
- **Connection status** — live state indicator (`not connected → awaiting
  approval → connected / error`) with an event log.
- **Address & network display** — user-friendly bounceable/non-bounceable
  forms, raw `workchain:hex` form, workchain, network (mainnet/testnet), wallet
  app, and one-click copy.
- **Session restore & disconnect** — an approved session survives app restarts
  and can be revoked from the UI.
- **Demo mode** — a clearly labelled mock wallet that simulates the full
  handshake offline, with no keys and no network access, for trying the UI.
- **Safe error handling** — wallet rejections, timeouts, unreachable bridges,
  and malformed manifest errors are surfaced as readable messages.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
ton-wallet-assistant        # or: python -m ton_wallet_assistant
```

Without any configuration the app starts in **demo mode** so you can click
through the complete connect/disconnect flow immediately.

### Demo mode vs. real mode

| | Demo mode | Real mode |
|---|---|---|
| Trigger | default when no manifest URL is set, or `--demo` | manifest URL configured |
| Wallet | built-in fake "Demo Wallet" | real TonConnect wallets |
| Network access | none | TonConnect bridge (SSE) + wallet registry |
| Keys | randomly generated throwaway data | ephemeral session keypair managed by `pytonconnect` |

Demo mode is always visibly labelled with a **DEMO MODE** badge and banner.
Nothing in demo mode touches the network or a real wallet.

## Connecting a real wallet

TonConnect dApps identify themselves to wallets with a small public manifest
file, `tonconnect-manifest.json`. To enable real connections:

1. Copy `assets/tonconnect-manifest.example.json` to `tonconnect-manifest.json`
   and fill in your app's name, URL, and icon.
2. Host it at a **public HTTPS URL** — for example via GitHub Pages,
   a `raw.githubusercontent.com` URL of a public repo, or any static host.
3. Point the app at it:

```bash
ton-wallet-assistant --manifest-url https://your-domain.example/tonconnect-manifest.json
# or persist it:
export TON_WALLET_ASSISTANT_MANIFEST_URL=https://your-domain.example/tonconnect-manifest.json
```

Then: pick a wallet in the list → **Connect** → scan the QR code with the
wallet (in Telegram, the *Wallet* bot opens `t.me/wallet?attach=wallet` links)
or use **Open in wallet / Telegram** for a desktop wallet → approve in the
wallet UI. The app shows the approved address and network.

**No credentials are required.** TonConnect needs no API key, bot token, or
seed phrase on the dApp side. The session keypair is generated per-connection
by `pytonconnect` and stored locally in
`~/.config/ton-wallet-connect-assistant/tonconnect-session.json`
(`%APPDATA%\ton-wallet-connect-assistant\` on Windows). Transaction signing
always happens inside the wallet — this app can only *request* connections.

### Configuration reference

| Source | Setting |
|---|---|
| `--manifest-url` / `TON_WALLET_ASSISTANT_MANIFEST_URL` / `manifest_url` in config | HTTPS URL of `tonconnect-manifest.json` (enables real mode) |
| `--demo` / `TON_WALLET_ASSISTANT_DEMO=1` / `demo: true` | force demo mode |
| `--demo-network` / `TON_WALLET_ASSISTANT_DEMO_NETWORK` / `demo_network` | `mainnet` or `testnet` for the demo wallet |

Config file: `~/.config/ton-wallet-connect-assistant/config.json`
(`%APPDATA%\ton-wallet-connect-assistant\config.json` on Windows), e.g.
`{"manifest_url": "https://your-domain.example/tonconnect-manifest.json"}`.

## Architecture

```
src/ton_wallet_assistant/
├── __main__.py            # CLI entry point (--manifest-url, --demo, --demo-network)
├── gui.py                 # PySide6 main window + asyncio/Qt bridge
├── config.py              # CLI > env > config-file resolution; no secrets here
├── models.py              # WalletOption, ConnectedAccount, ServiceEvent
├── address_utils.py       # raw ⇄ friendly TON address conversion (CRC16/base64url)
├── qr.py                  # universal-link → PNG QR rendering
└── services/
    ├── base.py            # WalletService interface (async, event-driven)
    ├── tonconnect.py      # real backend via pytonconnect (SSE bridge)
    └── demo.py            # offline mock backend, clearly labelled
```

The GUI runs wallet I/O on a dedicated asyncio thread and marshals events back
to Qt through signals, so the interface never blocks on the bridge listener.

## Tests & checks

```bash
pip install -e ".[dev]"
ruff check src tests
QT_QPA_PLATFORM=offscreen pytest -v
```

The suite covers address conversion against reference vectors, the demo
connect/disconnect cycle, config resolution, QR generation, and a headless
(offscreen) end-to-end GUI smoke test. CI runs lint + tests on Linux, Windows,
and macOS.

## Notes & limitations

- Transaction *requests* (`sendTransaction`) are supported by TonConnect but
  intentionally not surfaced in this app — it is a connection assistant only.
- The TON wallet registry is fetched over HTTPS at runtime; an offline fallback
  list built into `pytonconnect` is used when the fetch fails.
- `demo://` links are understood by nothing outside this app — they exist only
  to drive the simulated flow.
