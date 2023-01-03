from loguru import logger
from typing import List
from tree_sitter import Tree, Node
from pygls.server import LanguageServer
from pygls.lsp.types.basic_structures import Diagnostic, DiagnosticSeverity, Range, Position
from .hlparser import HELIOS_LANGUAGE


def get_missing_nodes(tree: Tree) -> List[Node]:
   """Traverses the entire tree and returns a list of missing nodes."""
   if not tree.root_node.children:
      return []

   missing_nodes = []

   def traverse_tree(node: Node):
      for n in node.children:
         if n.is_missing:
            missing_nodes.append(n)
         traverse_tree(n)

   traverse_tree(tree.root_node)

   return missing_nodes


def validate_document(ls: LanguageServer, uri: str, tree: Tree) -> None:
   """Checks the source for syntax errors and missing nodes."""
   logger.debug(f"TREE HAS ERROR: {tree.root_node.has_error}")

   query = HELIOS_LANGUAGE.query(
      """
      (ERROR) @error
      """
   )
   error_nodes = [node for node, _ in query.captures(tree.root_node)]
   missing_nodes = get_missing_nodes(tree)

   diagnostics = []

   for node in error_nodes + missing_nodes:
      d = Diagnostic(
         range=Range(
            start=Position(line=node.start_point[0], character=node.start_point[1]),
            end=Position(line=node.end_point[0], character=node.end_point[1])
         ),
         message="Syntax error" if node.type == "ERROR" else f"MISSING {node.type}",
         source="Helios" + type(ls).__name__,
         severity=DiagnosticSeverity.Error
      )
      diagnostics.append(d)

   ls.publish_diagnostics(uri, diagnostics)
