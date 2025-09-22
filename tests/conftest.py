import os
import sys


def pytest_sessionstart(session):
    # Обеспечиваем импорт пакета scraper при запуске pytest из корня
    project_root = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(project_root, os.pardir))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
