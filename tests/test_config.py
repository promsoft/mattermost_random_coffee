from coffeebot.config import Settings


def make_settings(**env) -> Settings:
    return Settings(_env_file=None, **env)


def test_driver_options_https_default_port():
    s = make_settings(mm_url="https://mm.example.com", mm_bot_token="tok")
    opts = s.driver_options
    assert opts["url"] == "mm.example.com"
    assert opts["scheme"] == "https"
    assert opts["port"] == 443
    assert opts["basepath"] == "/api/v4"
    assert opts["token"] == "tok"


def test_driver_options_explicit_port():
    s = make_settings(mm_url="http://localhost:8065")
    opts = s.driver_options
    assert opts["url"] == "localhost"
    assert opts["scheme"] == "http"
    assert opts["port"] == 8065


def test_db_url():
    s = make_settings(db_path="/data/coffee.db")
    assert s.db_url == "sqlite:////data/coffee.db"
