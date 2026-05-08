from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def load_qmt_provider():
    package_name = "python_bridge_l2_testpkg"
    root = Path(__file__).resolve().parent
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package

    provider_spec = importlib.util.spec_from_file_location(
        f"{package_name}.provider",
        root / "provider.py",
    )
    provider_module = importlib.util.module_from_spec(provider_spec)
    sys.modules[f"{package_name}.provider"] = provider_module
    assert provider_spec and provider_spec.loader
    provider_spec.loader.exec_module(provider_module)

    qmt_spec = importlib.util.spec_from_file_location(
        f"{package_name}.qmt_provider",
        root / "qmt_provider.py",
    )
    qmt_module = importlib.util.module_from_spec(qmt_spec)
    sys.modules[f"{package_name}.qmt_provider"] = qmt_module
    assert qmt_spec and qmt_spec.loader
    qmt_spec.loader.exec_module(qmt_module)
    return qmt_module


def test_frame_to_records_preserves_code_for_dict_of_dataframes():
    module = load_qmt_provider()

    class FakeFrame:
        def to_dict(self, orient):
            assert orient == "records"
            return [{"bidPrice1": 10.1, "bidVolume1": 100}]

    assert module.frame_to_records({"000001.SZ": FakeFrame()}) == [
        {"code": "000001.SZ", "bidPrice1": 10.1, "bidVolume1": 100}
    ]
