import re
from inspect import isclass
from typing import List, Type, cast
from tree_sitter import Node, Tree
from pygls.lsp.types.basic_structures import Range, Position
from pygls.lsp.types import Hover, HoverParams
from .helios_types import HeliosFunction, HeliosType 
from .hlparser import HELIOS_LANGUAGE
from .namespace import NamespaceParser, CACHED_EXPRESSIONS
from loguru import logger


class Hoverer:
   def __init__(self, ns_parser: NamespaceParser) -> None:
      self.ns_parser = ns_parser

   def node_from_word(self, tree: Tree, word: str, position: Position):
      line, char = position.line, position.character
      query = HELIOS_LANGUAGE.query(
         f""" 
            (identifier) @word 
            (#match? @word "{word}")
         """
      )
      result = query.captures(
         tree.root_node, start_point=(line, char), end_point=(line, char+1)
      )

      if not result:
         query = HELIOS_LANGUAGE.query(
            f""" 
            [
               (bool_type) @primitive.bool
               (int_type) @primitive.int
               (str_type) @primitive.str
               (bytearray_type) @primitive.bytearray
            ]
            """
         )
         result = query.captures(
            tree.root_node, start_point=(line, char), end_point=(line, char+1)
         )

      logger.debug(result[0][0])

      return result[0][0]

   def get_global_types(self) -> List[Type[HeliosType]]:
      return self.ns_parser.global_types

   def get_global_definitions(self) -> List[HeliosType | HeliosFunction]:
      return self.ns_parser.global_definitions

   def get_local_definitions(self) -> List[HeliosType | HeliosFunction]:
      return self.ns_parser.local_definitions

   def get_range(self, n: Node) -> Range:
      start_position = Position(line=n.start_point[0], character=n.start_point[1])
      end_position = Position(line=n.end_point[0], character=n.end_point[1])
      return Range(start=start_position, end=end_position)

   def parse_member_expr(self, id_node: Node, n: Node) -> Hover | None:
      l = list(map(lambda x: re.sub(r'\s+', '', x), n.text.decode('utf8').split('.')))
      expr_str, member_str = '.'.join(l[0:-1]), l[-1]
      helios_instance = next(filter(
         lambda i: i.identifier == expr_str, self.get_global_definitions() + self.get_local_definitions()
      ), None)
      if helios_instance:
         member = next(filter(lambda m: m.identifier == member_str, helios_instance.member_completions()), None)
         if not member:
            return
         detail = cast(str, member.completion_information_self()['detail'])
         return Hover(contents=detail, range=self.get_range(id_node))
      else:
         helios_instance = CACHED_EXPRESSIONS.get(expr_str) # check cache
         if not helios_instance:
            return
         member = next(filter(lambda m: m.identifier == member_str, helios_instance.member_completions()), None)
         if member:
            detail = cast(str, member.completion_information_self()['detail'])
            return Hover(contents=detail, range=self.get_range(id_node))

   def parse_value_ref_expr(self, id_node: Node, n: Node) -> Hover | None:
      n_str = n.text.decode('utf8')
      helios_instance = next(filter(
         lambda i: i.identifier == n_str, self.get_global_definitions() + self.get_local_definitions()
      ), None)
      if helios_instance:
         detail = cast(str, helios_instance.completion_information_self()['detail'])
         return Hover(contents=detail, range=self.get_range(id_node))

   def parse_ref_type(self, id_node: Node) -> Hover | None:
      """ref_type & struct_literal"""
      ref_type = next(filter(lambda t: t.type_name == id_node.text.decode('utf8'), self.get_global_types()), None)
      if ref_type:
         detail: str = cast(str, ref_type.completion_information_type()['detail'])
         return Hover(contents=detail, range=self.get_range(id_node))

   def parse_enum_struct(self, id_node: Node, n: Node) -> Hover | None:
      n_str = id_node.text.decode('utf8')
      return Hover(
         contents=f"({'struct' if n.type == 'struct_statement' else 'enum'}) {n_str}", 
         range=self.get_range(id_node)
      )

   def parse_value_path_expr(self, id_node: Node, n: Node) -> Hover | None:
      """value_path_expression & path_type"""
      l = list(map(lambda x: re.sub(r'\s+', '', x), n.text.decode('utf8').split('::')))
      type_str, member_str = l[0], l[-1]
      helios_type = next(filter(lambda t: t.type_name == type_str, self.get_global_types()), None)
      if helios_type:
         member = next(filter(lambda m: m.identifier == member_str, helios_type.path_completions()), None)
         if isclass(member):
            detail = cast(str, member().completion_information_self()['detail'])
            return Hover(contents=detail, range=self.get_range(id_node))
         else:
            member = cast(HeliosType, member)
            detail = cast(str, member.completion_information_self()['detail'])
            return Hover(contents=detail, range=self.get_range(id_node))

   def parse_parameter(self, id_node: Node, n: Node) -> Hover | None:
      l = list(map(lambda x: re.sub(r'\s+', '', x), n.text.decode('utf8').split(':')))
      param_str = l[0]
      helios_instance = next(filter(lambda i: i.identifier == param_str, self.get_local_definitions()), None)
      if helios_instance:
         detail = cast(str, helios_instance.completion_information_self()['detail'])
         return Hover(contents=detail, range=self.get_range(id_node))

   def parse_function(self, id_node: Node, n: Node, word: str) -> Hover | None:
      func_args = next(filter(lambda n: n.type == "func_args", n.named_children), None)
      return_type = next(filter(lambda n: n.type == "type", n.named_children))
      detail = (
         f"({'function' if n.type == 'function_statement' else 'method'}) "
         f"{word}: ({func_args.text.decode('utf8') if func_args else ''}) "
         f"-> {return_type.text.decode('utf8')}"
      )
      return Hover(contents=detail, range=self.get_range(id_node))

   def parse_data_field(self, id_node: Node, n: Node) -> Hover | None:
      l = list(map(lambda x: re.sub(r'\s+', '', x), n.text.decode('utf8').split(':')))
      field_str, type_str = l[0], l[1]
      detail = f"(field) {field_str}: {type_str}" 
      return Hover(contents=detail, range=self.get_range(id_node))
      
   def parse_enum_variant(self, id_node: Node, n: Node) -> Hover | None:
      n_str = n.text.decode('utf8')
      enum = n.parent
      enum_id = next(filter(lambda n: n.type == "identifier", enum.named_children)).text.decode('utf8')
      variant = list(map(lambda x: re.sub(r'\s+', '', x), n_str.split('{')))[0]
      detail = f"(enum variant) {variant}: {enum_id}::{variant}"
      return Hover(contents=detail, range=self.get_range(id_node))

   def infer_hover(self, tree: Tree, word: str, params: HoverParams) -> Hover | None:
      logger.debug(word)
      logger.debug(params.position)

      position = Position(line=params.position.line, character=params.position.character)
      id_node: Node = self.node_from_word(tree, word, position)

      if id_node.type in ('bool_type', 'int_type', 'str_type', 'bytearray_type'):
         primitive_type = next(filter(lambda t: t.type_name == id_node.text.decode('utf8'), self.get_global_types()))
         detail: str = cast(str, primitive_type.completion_information_type()['detail'])
         return Hover(contents=detail, range=self.get_range(id_node))

      n = cast(Node, id_node.parent)
      logger.debug(n)     

      match n.type:
         case "member_expression":
            return self.parse_member_expr(id_node, n)
         case "value_ref_expression":
            return self.parse_value_ref_expr(id_node, n)
         case "ref_type" | "struct_literal":
            return self.parse_ref_type(id_node)
         case "enum_statement" | "struct_statement":
            return self.parse_enum_struct(id_node, n)
         case "value_path_expression" | "path_type":
            return self.parse_value_path_expr(id_node, n)
         case "parameter":
            return self.parse_parameter(id_node, n)
         case "function_statement" | "method_statement":
            return self.parse_function(id_node, n, word)
         case "data_field":
            return self.parse_data_field(id_node, n)
         case "enum_variant":
            return self.parse_enum_variant(id_node, n)
