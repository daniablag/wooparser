import subprocess
import sys


def test_cli_help():
    proc = subprocess.run([sys.executable, "-m", "scraper", "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "CLI для парсинга" in proc.stdout


def test_imports():
    import scraper
    import scraper.main
    import scraper.models
    import scraper.config
    import scraper.store
