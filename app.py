"""Launch the local subtitle OCR application."""
import logging
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from subocr.ui import MainWindow, VideoCanvas, Worker, MergeDialog, STYLE, configure_app

ROOT = Path(__file__).resolve().parent


def main():
    logging.basicConfig(filename=ROOT / 'sublens.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
    application = QApplication(sys.argv)
    application.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / 'assets' / 'sublens.ico')))
    configure_app(application)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        window.open_video(sys.argv[1])
    return application.exec()


if __name__ == '__main__':
    sys.exit(main())
