"""
Pastikan setiap modul app/ bisa di-import.

Regresi yang dicegah: `reportlab` dipakai di level modul oleh
research_paper_engine.py tapi tidak ada di requirements.txt. Di venv lokal
kelihatan aman (paket sudah terpasang), tapi container/deploy gagal dengan
ModuleNotFoundError dan halaman utama jadi 500.

Test ini meng-import semua modul, jadi dependensi yang hilang langsung
ketahuan di CI, bukan saat user membuka halaman.
"""

import importlib
import pkgutil
import pathlib

import app


def _all_modules():
    root = pathlib.Path(app.__file__).parent
    for mod in pkgutil.walk_packages([str(root)], prefix="app."):
        name = mod.name
        # Lewati paket opsional yang memang butuh sistem eksternal.
        if "weasyprint" in name:
            continue
        yield name


def test_semua_modul_app_bisa_diimport():
    gagal = []
    for name in _all_modules():
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as e:
            gagal.append(f"{name}: {e}")
        except Exception:
            # Error lain (mis. butuh env) bukan masalah dependensi;
            # yang dicegah test ini hanya modul yang tidak bisa dimuat.
            pass
    assert not gagal, "Modul gagal di-import (dependensi hilang di requirements.txt?):\n" + "\n".join(gagal)
