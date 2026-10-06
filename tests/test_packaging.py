"""Anti-régression « exécutable compilé » : PyInstaller n'embarque que les modules atteignables par des instructions
`import` (même dans une fonction) depuis main.py — PAS ceux chargés par importlib.import_module("nom").
Cause du plantage de la v1.2.0 à la connexion : « No module named 'ui_reception' »."""
import ast, glob, json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def project_modules():
    return {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "*.py"))}


def static_imports(mod, mods):
    tree = ast.parse(open(os.path.join(ROOT, mod + ".py"), encoding="utf-8").read())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out & mods


class PackagingTests(unittest.TestCase):
    def test_every_project_module_is_statically_reachable_from_main(self):
        mods = project_modules(); seen, todo = set(), ["main"]
        while todo:
            m = todo.pop()
            if m not in seen:
                seen.add(m); todo += list(static_imports(m, mods))
        self.assertEqual(sorted(mods - seen), [], "modules absents de l'exécutable PyInstaller (import dynamique ?)")

    def test_no_dynamic_import_of_project_modules(self):
        for path in glob.glob(os.path.join(ROOT, "*.py")):
            src = open(path, encoding="utf-8").read()
            self.assertNotIn("import_module(", src, os.path.basename(path))
            self.assertNotIn("__import__(", src, os.path.basename(path))


class ConfigMigrationTests(unittest.TestCase):
    def test_old_configs_are_migrated_in_cascade(self):
        tmp = tempfile.mkdtemp(); os.environ.update({"LOCALAPPDATA": tmp, "HOME": tmp})
        from config_manager import Config, data_dir
        os.makedirs(data_dir(), exist_ok=True)
        path = os.path.join(data_dir(), "config.json")
        for old, expect_hours in (({"role": "medecin", "revisit_check_hours": 24}, 72),                       # v1.0.0 (sans config_version)
                                  ({"role": "radio", "revisit_check_hours": 24, "config_version": 2}, 24),    # v1.1.0 : l'utilisateur avait peut-être choisi 24 h
                                  ({"role": "dedie", "services": ["LAB"], "config_version": 3}, 72)):
            json.dump(old, open(path, "w")); c = Config()
            self.assertEqual(c.get("config_version"), 3)
            self.assertEqual(c.get("revisit_check_hours"), expect_hours)
            self.assertIn(c.get("role"), ("accueil", "dedie"))


if __name__ == "__main__":
    unittest.main()
