# TON Wallet Connect Assistant

A Tonkeeper-style **desktop TON wallet** in Python (PySide6/Qt) plus a headless
**Python SDK**, with a built-in
[TonConnect](https://docs.ton.org/applications/ton-connect/get-started) connection assistant — the link flow
used by Telegram's built-in **Wallet**, Tonkeeper, Tonhub, and other TON wallets.

## Features

### Wallet
- **Create / import** a TON wallet from a 24-word recovery phrase (v4r2 and
  v5r1 contracts supported).
- **Encrypted keystore** — the mnemonic is stored only on this machine,
  encrypted with your password (argon2id → NaCl SecretBox, file mode `0600`).
- **Balance & assets** — TON balance and multi-asset jetton list via
  tonapi.io, each with its own decimals and icon avatar.
- **Send** TON and jetton (TEP-74) transfers signed locally and broadcast over
  the lite-client protocol (pytoniq) — no API key required. The send dialog
  has an asset picker, balance-aware validation, and comment support; sends
  require the wallet password.
- **Receive** — address + `ton://transfer/…` QR code.
- **Collectibles** — NFT grid via tonapi.io (`/nfts`).
- **Transaction history** — incoming/outgoing TON and jetton transfers on a
  dedicated page; clicking a record opens full details (sender/recipient,
  amount, fee, comment, event hash, Tonviewer link).
- **Settings** — lock now, reveal recovery phrase (password required), delete
  wallet (password required), config paths.
- **Tonkeeper-style dark UI** — sidebar navigation (Wallet / History /
  Collectibles / TonConnect / Settings) with a dark theme.

### TonConnect tab
- Connect external wallets (Telegram Wallet, Tonkeeper, Tonhub, …) to the app
  as a dApp: wallet picker, universal link + QR, deep link, connection status,
  approved account display (address, network, workchain), disconnect, session
  restore.

### Demo mode
- Clearly labelled, fully offline mock: a demo wallet account, fake balances,
  jettons, history, and simulated sends. Nothing persists, nothing touches the
  network, and a **DEMO** badge is shown in the window title and tabs.

### Mobile companion (Pairing tab)
- **Pairing**: the app runs a tiny local HTTP bridge and shows a pairing URL +
  QR (`http://<lan-ip>:<port>/p/<token>`). Open it on your phone to get a
  mobile scanner page — camera scanning (BarcodeDetector API) plus a
  manual-paste fallback.
- **Relay**: scanned `tc://` / TonConnect universal links and `ton://transfer`
  payloads are POSTed to the desktop and queued — nothing executes on the phone.
- **Approval**: every relayed payload pops a desktop approval dialog showing
  origin, method, destination, amount/asset, comment, network, and estimated
  fee. Transfers need the wallet password and are signed by the encrypted
  keystore; TonConnect links are forwarded to the local wallet app.
- **Security model**: a fresh 256-bit pairing token per bridge start gates
  every request (path + `X-Pairing-Token` header); relay POSTs carry a
  single-use nonce + timestamp (±120 s skew) for replay protection; payloads
  are strictly validated; requests expire after 5 minutes.
- **Limitations**: plain HTTP on the LAN — pair only on trusted networks and
  verify the request details on the desktop before approving. No mTLS or
  device binding; anyone with the pairing URL on the LAN can submit payloads
  (they still require desktop approval). In demo mode the bridge binds to
  loopback only and executes nothing real.

### Telegram tab (TDLib, pure Python)
- Sign in to a Telegram account (phone → code → optional 2FA password),
  list chats, and watch incoming updates, right from the app or the SDK.
- **100% Python wrapper**: `telegram/tdjson.py` loads the prebuilt
  `libtdjson` shared library via `ctypes` at runtime — no Cython, no C/C++
  extension, no generated binding layer anywhere in the repo.
- **Credentials** come from the environment or the config file — never
  hardcoded and never logged (`api_hash` is masked in all diagnostics).
  Precedence: `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` env vars →
  `"telegram"` section of `config.json` (see `assets/config.example.json`
  — copy it to `~/.config/ton-wallet-connect-assistant/config.json` and
  fill in your own values from https://my.telegram.org). `TDLIB_PATH`
  overrides library discovery.
- **libtdjson discovery** (`telegram/loader.py`) searches, in order:
  `TDLIB_PATH` / config `tdlib_path` → macOS `.app` bundle dirs
  (`Contents/Frameworks`, `Resources`, `MacOS`) and PyInstaller
  `_MEIPASS` → the package directory → `lib/`/`libs`/`native`/`bin` next
  to the package and in the working directory → the OS loader
  (`find_library`, then the bare platform filename). The load error lists
  every path tried.
- To bundle: drop the prebuilt binary next to the executable —
  `Contents/Frameworks/libtdjson.dylib` in a `.app`, `tdjson.dll` beside
  the `.exe`, or `lib/`/`libtdjson.so` next to a checkout — it is found
  automatically.
- Demo mode simulates the entire flow offline — phone, code `12345`,
  chats, and message updates — clearly labelled, no network.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[gui]"    # desktop app; plain `pip install -e .` = SDK only
ton-wallet-assistant        # or: python -m ton_wallet_assistant
```

First launch shows onboarding: **Create new wallet** → back up the 24-word
phrase → set a password; or **Import existing wallet**; or **Try demo mode**.

On later launches, enter the password to unlock the encrypted keystore.

### Demo mode vs. real mode

| | Demo | Real |
|---|---|---|
| Wallet | randomly generated, in-memory only | your wallet, encrypted keystore on disk |
| Balances/history | fabricated | tonapi.io (mainnet/testnet) |
| Sends | simulated | signed locally, broadcast via TON lite-servers |
| Network access | none | tonapi.io + lite-servers (+ TonConnect bridge if configured) |

Demo mode is always visibly labelled. Start it with `--demo`, or from the
onboarding screen.

## Python SDK

The wallet core is usable headlessly — no Qt/PySide6 required (it's an optional
`gui` extra). `TonWalletSDK` covers wallet create/import/keystore management,
balances, TON + jetton (TEP-74) sends, NFTs, history, and the TonConnect
session lifecycle:

```python
import asyncio
from ton_wallet_assistant.sdk import TonWalletSDK

async def main():
    sdk = await TonWalletSDK.demo()          # fully offline — fake data only
    print(sdk.account.friendly_bounceable)
    print(await sdk.get_balance_ton(), "TON")
    await sdk.send_ton("UQAAAA…", "1.5")      # simulated in demo mode
    await sdk.close()

asyncio.run(main())
```

Real-mode sketch (writes the encrypted keystore to `~/.config/…` or `data_dir=`):

```python
sdk = TonWalletSDK(network="mainnet", manifest_url="https://example.com/manifest.json")
words, account = await sdk.create_wallet(password="…")   # back up `words` once
await sdk.unlock_and_derive("…")                          # later sessions
await sdk.send_ton(destination, "0.1", comment="hi")
await sdk.send_jetton("USDT", destination, "25")        # TEP-74 via jetton wallet
await sdk.send_jetton(jetton_balance_obj, destination, "25")  # or pass the object
await sdk.close()
```

TonConnect (dApp side):

```python
wallets = await sdk.tonconnect.list_wallets()
link = await sdk.tonconnect.request_connection(wallets[0])  # show as QR/link
account = await sdk.tonconnect.wait_for_connection()        # pending → connected
await sdk.tonconnect.disconnect()
```

Low-level builders (offline message construction): `sdk.build_transfer_body(comment)`,
`sdk.build_jetton_transfer(dest, units, response_addr, comment=…)`.

Mobile companion pairing:

```python
url = await sdk.start_pairing()          # http://<lan-ip>:<port>/p/<token>
async for req in sdk.pairing_requests(): # relayed payloads from the phone
    if looks_good(req):                  # GUI shows the approval dialog here
        await sdk.approve_pairing_request(req.request_id, password="…")
    else:
        sdk.reject_pairing_request(req.request_id)
```

Telegram (TDLib — pure-Python ctypes over libtdjson, no Cython/C extensions):

```python
tg = sdk.telegram                      # demo → offline DemoTelegramClient
await tg.start()                       # real: TdJsonClient from env config
await tg.submit_phone("+15551234567")
await tg.submit_code("12345")          # demo code; real mode uses SMS
await tg.get_chats(); await tg.send_message(chat_id, "hi")
async for update in tg.updates(): ...
```

See `examples/sdk_demo.py`, `examples/pairing_demo.py`, and
`examples/telegram_demo.py` for runnable walkthroughs.

Security: mnemonics/keys are never logged; the decrypted mnemonic exists in
memory only between `unlock_and_derive()` and `lock()`/`close()`. Demo mode
(`TonWalletSDK.demo()` / `demo=True`) never touches the network and is always
clearly labelled.

## Real-mode configuration

| Source | Setting |
|---|---|
| `--network` / `TON_WALLET_ASSISTANT_NETWORK` / `network` in config | `mainnet` (default) or `testnet` |
| `--demo` / `TON_WALLET_ASSISTANT_DEMO=1` / `demo: true` | force demo mode |
| `--demo-network` / `TON_WALLET_ASSISTANT_DEMO_NETWORK` | network for the demo wallet |
| `--manifest-url` / `TON_WALLET_ASSISTANT_MANIFEST_URL` / `manifest_url` | HTTPS URL of `tonconnect-manifest.json` (enables real TonConnect sessions) |
| `TONAPI_KEY` env | optional tonapi.io API key for higher rate limits |

Config file: `~/.config/ton-wallet-connect-assistant/config.json`
(`%APPDATA%\ton-wallet-connect-assistant\config.json` on Windows).
Keystore: `keystore-<network>.json` in the same directory (owner-only `0600`).

**No private keys or seeds are ever needed in configuration.** The recovery
phrase lives only in the encrypted keystore; signing keys exist in memory only
while a transaction is being signed.

## TonConnect setup

The TonConnect tab connects *external* wallets to this app as a dApp. For real
connections, host `tonconnect-manifest.json` at a public HTTPS URL (see
`assets/tonconnect-manifest.example.json`, e.g. via GitHub Pages) and set
`--manifest-url` / `TON_WALLET_ASSISTANT_MANIFEST_URL`. Without it the tab runs
in demo mode.

Official references:

- [TON Connect documentation](https://docs.ton.org/applications/ton-connect/get-started)
- [Protocol spec / repository](https://github.com/ton-blockchain/ton-connect)
- [SDK reference](https://ton-connect.github.io/sdk/index.html)

## Architecture

```
src/ton_wallet_assistant/
├── __main__.py            # CLI: --network, --demo, --demo-network, --manifest-url
├── config.py              # CLI > env > config-file resolution (no secrets)
├── session.py             # WalletSession: account + keystore + chain + connect service
├── models.py              # TonConnect event models
├── address_utils.py       # raw ⇄ friendly TON address conversion (CRC16/base64url)
├── qr.py                  # link/address → PNG QR
├── sdk.py                 # TonWalletSDK: headless wallet + TonConnect facade
├── wallet/
│   ├── account.py         # mnemonic validation, keypair, v4r2/v5r1 address derivation
│   ├── keystore.py        # argon2id + SecretBox encrypted mnemonic file
│   ├── chain.py           # ChainClient interface, TxRecord, JettonBalance, Nft, amount utils
│   ├── tonapi.py          # tonapi.io reads: balance, jettons, NFTs, history
│   ├── jettons.py         # TEP-74 jetton transfer body + amount conversion
│   ├── sender.py          # pytoniq lite-client TON + jetton transfer broadcast
│   └── demo.py            # fabricated offline backend for demo mode
├── services/              # TonConnect (dApp-side) backends: real + demo
├── companion/             # mobile companion: LAN bridge + pairing protocol
│   ├── protocol.py        # token auth, payload validation, replay protection
│   ├── server.py          # threaded HTTP bridge (token-gated endpoints)
│   ├── scanner_page.py    # self-contained mobile QR scanner page
│   └── manager.py         # request queue + approval state machine
├── telegram/              # Telegram client — pure Python + ctypes libtdjson
│   ├── config.py          # env config (TELEGRAM_API_ID/HASH, TDLIB_PATH)
│   ├── client.py          # TelegramClient ABC + auth state machine
│   ├── tdjson.py          # ctypes wrapper + async client (no Cython/C ext)
│   └── demo.py            # offline demo client (code 12345)
└── gui/
    ├── async_loop.py      # asyncio thread bridged to Qt signals
    ├── theme.py           # dark Tonkeeper-style stylesheet
    ├── icons.py           # deterministic letter-avatar asset/NFT icons
    ├── onboarding.py      # create / import / unlock / demo screens
    ├── wallet_tab.py      # balance, assets, send/receive (asset picker)
    ├── history_tab.py     # transaction list + details dialog
    ├── collectibles_tab.py# NFT grid
    ├── connect_tab.py     # TonConnect wallet-connect flow
    ├── companion_tab.py   # mobile pairing: bridge control + approvals
    ├── telegram_tab.py    # Telegram TDLib auth + chats + update feed
    ├── settings_tab.py    # lock, reveal phrase, delete wallet, config info
    ├── dialogs.py         # password / send-confirm / receive / tx details /
                           # relayed-request approval
    └── main_window.py     # session gating + sidebar navigation
```

The GUI runs wallet and chain I/O on a dedicated asyncio thread and marshals
events back to Qt through signals, so the interface never blocks.

### Security notes

- The mnemonic is encrypted at rest (argon2id KDF → XSalsa20-Poly1305) and the
  keystore file is owner-only (`0600`). It is decrypted in memory only when
  signing or revealing the phrase — always behind the password.
- The send flow always shows a confirmation dialog (destination, amount, fee)
  and requires the wallet password before signing.
- Nothing sensitive is written to logs: the app log shows events, never keys,
  mnemonic words, or passwords.
- Secrets must never be committed; tests use a throwaway generated mnemonic.

## Tests & checks

```bash
pip install -e ".[dev]"
ruff check src tests
QT_QPA_PLATFORM=offscreen pytest -v
```

Coverage: raw⇄friendly address vectors (checked against pytoniq-core), mnemonic
validation and deterministic address derivation (v4r2/v5r1, mainnet/testnet),
keystore encryption round-trip/permissions/wrong-password, amount parsing,
TEP-74 jetton transfer body construction, tonapi action parsing, demo chain
client (TON + jetton sends, NFTs), SDK public-API tests (importable without
PySide6, demo wallet flow, keystore create/unlock/send, TonConnect demo
lifecycle), companion pairing (token auth, payload validation, nonce/timestamp
replay protection, approval state machine, HTTP endpoints, SDK demo flow),
Telegram TDLib (env config validation, ctypes request/response + auth states +
update dispatch + errors + shutdown against an in-process fake libtdjson, demo
client flow, no-native-code guard), and a headless (offscreen) end-to-end GUI
flow across all pages. CI runs lint + tests on Linux, Windows, and macOS.

## Notes & limitations

- Jetton sends are implemented (TEP-74 through the owner's jetton wallet);
  NFT transfers, multisig, and staking are not (yet).
- TonConnect here is the dApp-side flow (connect an external wallet to this
  app). Acting as a TonConnect *wallet* for third-party dApps is future work.
- On air-gapped or restricted networks, real mode needs outbound access to
  tonapi.io (reads) and TON lite-servers (sends); the TonConnect tab also uses
  the SSE bridge.
- The Telegram tab requires a prebuilt `libtdjson` binary at runtime (the only
  non-Python component — loaded via ctypes; nothing compiled at build time and
  no Cython/native wrapper in this repo). User-account auth via TDLib requires
  your own api_id/api_hash from https://my.telegram.org.
