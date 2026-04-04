"""Import parsing helpers used by build graph and test selection."""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

from monopack.module_resolver import resolve_module_to_file


@dataclass(frozen=True)
class ImportRef:
    """Normalized import reference extracted from a module."""

    module: str | None
    level: int
    imported_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelativeImportRef(ImportRef):
    """Import reference that originated from a relative import."""

    level: int


def _is_type_checking_guard(test: ast.AST) -> bool:
    """Return True when an ``if`` guard is a TYPE_CHECKING block."""

    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"

    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return isinstance(test.value, ast.Name) and test.value.id == "typing"

    return False


class _ImportCollector(ast.NodeVisitor):
    """AST visitor that captures import statements outside TYPE_CHECKING guards."""

    def __init__(self) -> None:
        self.refs: list[ImportRef] = []
        self._skip_stack: list[bool] = [False]

    def visit_If(self, node: ast.If) -> None:
        current_skip = self._skip_stack[-1]
        body_skip = current_skip or _is_type_checking_guard(node.test)

        self._skip_stack.append(body_skip)
        for statement in node.body:
            self.visit(statement)
        self._skip_stack.pop()

        self._skip_stack.append(current_skip)
        for statement in node.orelse:
            self.visit(statement)
        self._skip_stack.pop()

    def visit_Import(self, node: ast.Import) -> None:
        if self._skip_stack[-1]:
            return

        for alias in node.names:
            self.refs.append(ImportRef(module=alias.name, level=0))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._skip_stack[-1]:
            return

        imported_names = tuple(alias.name for alias in node.names)
        if node.level > 0:
            self.refs.append(
                RelativeImportRef(
                    module=node.module,
                    level=node.level,
                    imported_names=imported_names,
                )
            )
            return

        if node.module is not None:
            self.refs.append(
                ImportRef(
                    module=node.module,
                    level=0,
                    imported_names=imported_names,
                )
            )

    def visit_Call(self, node: ast.Call) -> None:
        if self._skip_stack[-1]:
            return

        literal_module = _literal_dynamic_import_module(node)
        if literal_module is not None:
            self.refs.append(ImportRef(module=literal_module, level=0))

        self.generic_visit(node)


def _literal_dynamic_import_module(node: ast.Call) -> str | None:
    """Return module string for supported literal dynamic import call forms."""

    if not node.args:
        return None

    first_arg = node.args[0]
    if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
        return None

    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
        return first_arg.value

    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != "import_module":
        return None
    if not isinstance(node.func.value, ast.Name):
        return None
    if node.func.value.id != "importlib":
        return None

    return first_arg.value


def extract_import_references_from_file(path: Path) -> list[ImportRef]:
    """Parse a Python file and return collected import references."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    collector = _ImportCollector()
    collector.visit(tree)
    return collector.refs


def extract_imports_from_file(path: Path) -> set[str]:
    """Return absolute imported module names from a Python source file."""

    modules: set[str] = set()
    for ref in extract_import_references_from_file(path):
        if ref.level == 0 and ref.module is not None:
            modules.add(ref.module)

    return modules


def root_module(name: str) -> str:
    """Return the top-level module portion of a dotted name."""

    return name.split(".", 1)[0]


def classify_roots(
    modules: set[str],
    project_root: Path,
) -> tuple[set[str], set[str], set[str]]:
    """Split modules into local-first-party, stdlib, and third-party roots."""

    first_party: set[str] = set()
    stdlib: set[str] = set()
    third_party: set[str] = set()

    unresolved_roots: set[str] = set()

    for module in modules:
        root = root_module(module)
        if resolve_module_to_file(module, project_root) is not None:
            first_party.add(root)
        elif root in sys.stdlib_module_names:
            stdlib.add(root)
        else:
            unresolved_roots.add(root)

    third_party = unresolved_roots - first_party

    return first_party, stdlib, third_party
