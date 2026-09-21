# TON Wallet Connect Assistant

A Tonkeeper-style **desktop TON wallet** in Python (PySide6/Qt) with a built-in
[TonConnect](https://docs.ton.org/applications/ton-connect/) connection assistant — the link flow
used by Telegram's built-in **Wallet**, Tonkeeper, Tonhub, and other TON wallets.

## Features

### Wallet
- **Create / import** a TON wallet from a 24-word recovery phrase (v4r2 and
  v5r1 contracts supported).
- **Encrypted keystore** — the mnemonic is stored only on this machine,
  encrypted with your password (argon2id → NaCl SecretBox, file mode `0600`).
- **Balance & assets** — TON balance and jetton balances via tonapi.io.
- **Send** TON transfers signed locally and broadcast over the lite-client
  protocol (pytoniq) — no API key required. Sends require the wallet password.
- **Receive** — address + `ton://transfer/…` QR code.
- **Transaction history** — incoming/outgoing TON and jetton transfers.
- **Settings** — lock now, reveal recovery phrase (password required), delete
  wallet (password required), config paths.

### TonConnect tab
- Connect external wallets (Telegram Wallet, Tonkeeper, Tonhub, …) to the app
  as a dApp: wallet picker, universal link + QR, deep link, connection status,
  approved account display (address, network, workchain), disconnect, session
  restore.

### Demo mode
- Clearly labelled, fully offline mock: a demo wallet account, fake balances,
  jettons, history, and simulated sends. Nothing persists, nothing touches the
  network, and a **DEMO** badge is shown in the window title and tabs.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
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

- [TON Connect documentation](https://docs.ton.org/applications/ton-connect/)
  ([getting started](https://docs.ton.org/applications/ton-connect/get-started))
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
├── wallet/
│   ├── account.py         # mnemonic validation, keypair, v4r2/v5r1 address derivation
│   ├── keystore.py        # argon2id + SecretBox encrypted mnemonic file
│   ├── chain.py           # ChainClient interface, TxRecord, JettonBalance, amount utils
│   ├── tonapi.py          # tonapi.io reads: balance, jettons, history
│   ├── sender.py          # pytoniq lite-client transfer broadcast
│   └── demo.py            # fabricated offline backend for demo mode
├── services/              # TonConnect (dApp-side) backends: real + demo
└── gui/
    ├── async_loop.py      # asyncio thread bridged to Qt signals
    ├── onboarding.py      # create / import / unlock / demo screens
    ├── wallet_tab.py      # balance, assets, send/receive, history
    ├── connect_tab.py     # TonConnect wallet-connect flow
    ├── settings_tab.py    # lock, reveal phrase, delete wallet, config info
    ├── dialogs.py         # password / send-confirm / receive / seed dialogs
    └── main_window.py     # session gating + tab container
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
tonapi action parsing, demo chain client, the TonConnect demo cycle, and a
headless (offscreen) end-to-end GUI flow. CI runs lint + tests on Linux,
Windows, and macOS.

## Notes & limitations

- The wallet targets personal TON use: TON transfers and jetton *viewing* are
  implemented; jetton/NFT *transfers*, multisig, and staking are not (yet).
- TonConnect here is the dApp-side flow (connect an external wallet to this
  app). Acting as a TonConnect *wallet* for third-party dApps is future work.
- On air-gapped or restricted networks, real mode needs outbound access to
  tonapi.io (reads) and TON lite-servers (sends); the TonConnect tab also uses
  the SSE bridge.
