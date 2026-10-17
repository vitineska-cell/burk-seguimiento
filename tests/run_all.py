"""Ejecuta automáticamente todos los tests sin dependencias de desarrollo."""
import runpy
import unittest
from pathlib import Path

suite = unittest.TestSuite()
for path in sorted(Path(__file__).parent.glob('test_*.py')):
    module = runpy.run_path(str(path))
    for name, function in module.items():
        if name.startswith('test_') and callable(function):
            suite.addTest(unittest.FunctionTestCase(function, description=f'{path.name}:{name}'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
