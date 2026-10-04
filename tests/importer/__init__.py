"""The Library Importer: reading a library from another frontend, and importing it."""

from pathlib import Path

from common import i18n

i18n.own("ext.library_importer",
         Path(__file__).resolve().parents[2] / "extensions" / "library_importer" / "i18n")
