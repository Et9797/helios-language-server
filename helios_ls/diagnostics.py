"""Provides basic syntax error diagnostics."""

from typing import List, Tuple
from tree_sitter import Tree, Node
from pygls.server import LanguageServer
from pygls.lsp.types.basic_structures import Diagnostic, DiagnosticSeverity, Range, Position
from .hlparser import HELIOS_LANGUAGE
from loguru import logger


def get_diagnostic(node: Node, message: str) -> Diagnostic:
   return Diagnostic(
      range=Range(
         start=Position(line=node.end_point[0], character=node.end_point[1]),
         end=Position(line=node.end_point[0], character=node.end_point[1]+1)
      ),
      message=message,
      source="HeliosLanguageServer",
      severity=DiagnosticSeverity.Error
   )


def get_error_nodes(tree: Tree) -> List[Node]:
   query = HELIOS_LANGUAGE.query(
      """
      (ERROR) @error
      """
   )
   error_nodes = [node for node, _ in query.captures(tree.root_node)]
   error_nodes = list(filter(lambda n: (n.start_point[0], n.start_point[1]) != (0, 0), error_nodes))

   return error_nodes


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


def get_dummy_nodes(tree: Tree) -> List[Node]:
   query = HELIOS_LANGUAGE.query(
      """
      (dummy_token) @dummy
      """
   )
   dummy_nodes = [node for node, _ in query.captures(tree.root_node)]
   return dummy_nodes


# grammar for assignments, print, if-else was adapted to improve error tolerance,
# therefore required to handle these separately

def handle_print_and_assignment_nodes(tree: Tree) -> List[Node]:
   query = HELIOS_LANGUAGE.query(
      """
      [
         (print_expression) @print
         (assignment_expression) @assign
      ]
      """
   )
   nodes = [node for node, _ in query.captures(tree.root_node)]
   invalid_prints_and_assignments = [] # store prints & assignments missing ;
   for node in nodes:
      if not any(n.type == "terminator" for n in node.named_children):
         invalid_prints_and_assignments.append(node)

   return invalid_prints_and_assignments


def handle_ifelse_nodes(tree: Tree) -> List[Tuple[Node, str]]:
   query = HELIOS_LANGUAGE.query(
      """
      (ifelse_expression) @ifelse
      """
   )
   nodes = [node for node, _ in query.captures(tree.root_node)]
   invalid_ifelse = [] # store ifelse exprs missing block/else statement
   for node in nodes:
      if not any(n.type == "block" for n in node.named_children):
         invalid_ifelse.append((node, 'block'))
      if not any(n.type == "else" for n in node.children):
         invalid_ifelse.append((node, 'else'))

   return invalid_ifelse


def validate_document(ls: LanguageServer, uri: str, tree: Tree) -> None:
   """Checks the source for syntax errors."""
   logger.debug(f"TREE HAS ERROR: {tree.root_node.has_error}")

   error_nodes = get_error_nodes(tree)
   missing_nodes = get_missing_nodes(tree)
   dummy_nodes = get_dummy_nodes(tree)

   diagnostics = []

   for node in error_nodes + missing_nodes + dummy_nodes:
      diagnostics.append(get_diagnostic(
         node=node, message=(
            f"{'Syntax error' if node.type in ('ERROR', 'dummy_token') else f'MISSING {node.type}'}"
         )
      ))

   invalid_prints_and_assignments = handle_print_and_assignment_nodes(tree)
   for node in invalid_prints_and_assignments:
      diagnostics.append(get_diagnostic(
         node=node, message=f"MISSING ; after {'print' if node.type == 'print_expression' else 'assignment'}"
      ))

   invalid_ifelse = handle_ifelse_nodes(tree)
   for node in invalid_ifelse:
      diagnostics.append(get_diagnostic(
         node=node[0], message=f"MISSING {'block' if node[1] == 'block' else 'else statement'}"
      ))

   ls.publish_diagnostics(uri, diagnostics)
