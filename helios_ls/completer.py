import re
from inspect import isclass
from types import NoneType
from typing import List, Tuple, Union, cast
from typing_extensions import Literal
from tree_sitter import Tree, Node
from pygls.lsp.types import (
   CompletionItem, CompletionParams, CompletionItemKind,
   HoverParams, SignatureHelpParams, InsertTextFormat
)
from .hlparser import HELIOS_LANGUAGE
from .namespace import NamespaceParser, GLOBALS, VALUE_EXPRESSIONS
from .helios_types import CompletionInformation, HeliosFunction, HeliosType
from loguru import logger


Line, Char = int, int
Position = Tuple[Line, Char]
TriggerCharacter = Literal['.', '::']
LSFeatureParams = Union[CompletionParams, SignatureHelpParams, HoverParams]


class Completer:
   def __init__(self, ns_parser: NamespaceParser) -> None:
      self.ns_parser = ns_parser

   def create_completion_item(self, completion_information: CompletionInformation) -> CompletionItem:
      label = cast(str, completion_information["label"])
      kind = cast(CompletionItemKind, completion_information["kind"])
      detail = cast(str, completion_information["detail"])
      documentation = cast(Union[str, None], completion_information.get("documentation"))
      snippet = None
      if kind.name in ("Function", "Method"):
         if label in ("error", "print"):
            snippet = f"{label}($0)"
         else:
            pattern = re.compile(r'\W\((.*)\)')
            if re.findall(pattern, detail)[0]:
               snippet = f"{label}($0)"
            else:
               snippet = f"{label}()$0"
      elif label == "switch":
         snippet = f"{label} {{$0}}"
      return CompletionItem(
         label=label,
         kind=kind,
         detail=detail,
         documentation=documentation,
         insert_text=snippet,
         insert_text_format=InsertTextFormat.Snippet
      )

   def completions_trigger_char(self, trigger_node: Node) -> List[CompletionItem]:
      """Temporary solutions for parser error intolerance."""
      parent_node = trigger_node.parent
      logger.debug(parent_node)

      if not parent_node:
         return []

      if parent_node.type == "ERROR":
         if parent_node.named_children:
            value_expr_nodes = list(filter(lambda n: n.type in VALUE_EXPRESSIONS, parent_node.named_children))
            logger.debug(value_expr_nodes)
            if not value_expr_nodes:
               nonfunc_type = next(filter(lambda n: n.type == "nonfunc_type", parent_node.named_children), None)
               if not nonfunc_type:
                  return []
               else:
                  type = self.ns_parser.parse_nonfunc_type(nonfunc_type)
                  if not type:
                     return []
                  else:
                     expr = type()
                     logger.debug(expr)
            else:
               helios_instance = self.ns_parser.infer_expr_type(value_expr_nodes[-1])
               if isinstance(helios_instance, (HeliosFunction, NoneType)):
                  return []
               else:
                  expr = helios_instance
                  logger.debug(expr)
         else:
            nonfunc_type = parent_node.prev_named_sibling.named_children[0]
            logger.debug(nonfunc_type)
            type = self.ns_parser.parse_nonfunc_type(nonfunc_type)
            if not type:
               return []
            else:
               logger.debug(type)
               member_types = [t for t in type.path_completions() if isclass(t)]
               return [
                  self.create_completion_item(t().completion_information_self())
                  for t in member_types
               ]
      else:
         expr = (
            self.ns_parser.infer_expr_type(parent_node)
            if parent_node.type != "path_type"
            else self.ns_parser.parse_value_path_expression(parent_node)
         )
         if not expr:
            return []
         logger.debug(expr)

      if trigger_node.type == '.':
         expr = cast(Union[HeliosType, HeliosFunction], expr)
         if isinstance(expr, HeliosFunction):
            return [] # function has to be called in order to be able to use .
         return [
            self.create_completion_item(item.completion_information_self())
            for item in expr.member_completions()
         ]
      elif trigger_node.type == '::':
         completions = []
         for item in expr.path_completions():
            if isclass(item):
               completions.append(item().completion_information_self())
            else:
               completions.append(item.completion_information_self())
         return [self.create_completion_item(item) for item in completions]

   def completions_no_trigger_char(self) -> List[CompletionItem]:
      completions_globals = [item.completion_information_self() for item in GLOBALS]
      completions_global_types = [type.completion_information_type() for type in self.ns_parser.global_types]
      completions_global_definitions = [item.completion_information_self() for item in self.ns_parser.global_definitions]
      completions_local_definitions = [item.completion_information_self() for item in self.ns_parser.local_definitions]
      return [
         self.create_completion_item(ci)
         for ci in (
            completions_globals + completions_global_types + completions_global_definitions + completions_local_definitions
         )
      ]

   def infer_completions(
      self, tree: Tree, position: Position, trigger_char: TriggerCharacter | None = None
   ) -> List[CompletionItem]:
      """Infers completion items from the node types in the syntax tree."""
      self.ns_parser.parse_namespace(tree, position)

      if not trigger_char:
         global_completion_items = self.completions_no_trigger_char()

         line, char = position
         query = HELIOS_LANGUAGE.query("""(identifier) @trigger""")
         nodes: List[Tuple[Node, str]] = query.captures(
            tree.root_node, start_point=(line, char), end_point=(line, char+1)
         )

         if not nodes:
            return global_completion_items

         identifier: Node = nodes[0][0]
         trigger_node = identifier.prev_sibling

         if not trigger_node:
            return global_completion_items

         if trigger_node.type in ('.', '::'):
            trigger_completion_items = self.completions_trigger_char(trigger_node)
            return trigger_completion_items + global_completion_items
         else:
            return global_completion_items
      else:
         line, char = position
         query = HELIOS_LANGUAGE.query(f"""("{trigger_char}") @trigger""")
         trigger_node: Node = query.captures(
            tree.root_node, start_point=(line, char), end_point=(line, char+1)
         )[0][0]
         logger.debug(trigger_node)
         return self.completions_trigger_char(trigger_node)

   @staticmethod
   def position_from_params(params: LSFeatureParams) -> Position:
      line = params.position.line
      char = params.position.character - 1
      return (line, char)
