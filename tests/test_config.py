from ton_wallet_assistant.config import (
    ENV_DEMO,
    ENV_MANIFEST_URL,
    AppConfig,
)


def test_demo_forced_without_manifest():
    cfg = AppConfig.resolve(env={}, file_config={})
    assert cfg.demo_mode is True
    assert cfg.manifest_url is None
    assert cfg.real_connect_available is False


def test_manifest_from_env_enables_real_mode():
    env = {ENV_MANIFEST_URL: "https://example.com/tonconnect-manifest.json"}
    cfg = AppConfig.resolve(env=env, file_config={})
    assert cfg.demo_mode is False
    assert cfg.real_connect_available is True
    assert cfg.manifest_url.endswith("tonconnect-manifest.json")


def test_demo_flag_overrides_manifest():
    env = {ENV_MANIFEST_URL: "https://example.com/m.json", ENV_DEMO: "1"}
    cfg = AppConfig.resolve(env=env, file_config={})
    assert cfg.demo_mode is True
    assert cfg.real_connect_available is False


def test_cli_args_take_precedence():
    cfg = AppConfig.resolve(
        manifest_url="https://cli.example/m.json",
        demo=True,
        env={},
        file_config={"manifest_url": "https://file.example/m.json"},
    )
    assert cfg.manifest_url == "https://cli.example/m.json"
    assert cfg.demo_mode is True


def test_demo_network_normalization():
    cfg = AppConfig.resolve(demo_network="bogus", env={}, file_config={})
    assert cfg.demo_network == "mainnet"
    cfg = AppConfig.resolve(demo_network="testnet", env={}, file_config={})
    assert cfg.demo_network == "testnet"
