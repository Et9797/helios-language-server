import re
from inspect import isclass
from typing import Tuple, Union, Type, cast
from tree_sitter import Node, Tree
from pygls.lsp.types.basic_structures import MarkupContent, Position
from pygls.lsp.types import SignatureHelp, SignatureInformation, SignatureHelpParams, ParameterInformation
from pygls.workspace import Document
from .helios_types import HeliosFunction, HeliosType
from .hlparser import HELIOS_LANGUAGE
from .namespace import NamespaceParser, CACHED_EXPRESSIONS
from loguru import logger


TypeSignature = str
Documentation = str | MarkupContent


class SignatureHelper:
   def __init__(self, ns_parser: NamespaceParser) -> None:
      self.ns_parser = ns_parser

   def node_from_position(self, tree: Tree, trigger_char: str, position: Position) -> Node | None:
      """Returns a call_expression/struct_literal node from trigger character & position."""
      line, char = position.line, position.character
      query = HELIOS_LANGUAGE.query(f"""("{trigger_char}") @trigger""")
      result = query.captures(
         tree.root_node, start_point=(line, char), end_point=(line, char+1)
      )

      if not result:
         return

      n = result[0][0].parent # gets the actual call_expression/struct literal node

      logger.debug(n)
      logger.debug(n.text)

      return n if n.type in ("call_expression", "struct_literal") else None

   def active_index_from_node(self, node: Node) -> int:
      """Checks how many comma characters are inside {} or () and returns the corresponding 
      active parameter index."""
      if node.type == "call_expression":
         c = list(map(lambda x: re.sub(r'\s+', '', x), node.text.decode('utf8').split('.')))[-1]
         return c.count(',')
      elif node.type == "struct_literal":
         return node.text.decode('utf8').count(',')

   def parse_call_expr(self, node: Node) -> Tuple[TypeSignature, Documentation] | TypeSignature | None:
      """Parses the call_expression and returns the function's type signature, provided it is a valid member."""
      n = node.named_children[0] # get the member_expression/value_path_expression node in order to get rid of `()`
      if n.type == "value_ref_expression":
         n_str = n.text.decode('utf8')
         helios_instance = next(filter(
            lambda i: i.identifier == n_str, self.ns_parser.global_definitions + self.ns_parser.local_definitions
         ), None)
         if not helios_instance:
            return
         detail = cast(str, helios_instance.completion_information_self()['detail'])
         type_sig = detail.split(': ', 1)[1]
         return type_sig
      elif n.type == "value_path_expression":
         l = list(map(lambda x: re.sub(r'\s+', '', x), n.text.decode('utf8').split('::')))
         type_str, member_str = l[0], l[-1]
         helios_type = next(filter(lambda t: t.type_name == type_str, self.ns_parser.global_types ), None)
         if not helios_type:
            return
         member = next(filter(lambda m: m.identifier == member_str, helios_type.path_completions()), None)
      elif n.type == "member_expression":
         l = list(map(lambda x: re.sub(r'\s+', '', x), n.text.decode('utf8').split('.')))
         expr_str, member_str = '.'.join(l[0:-1]), l[-1]

         helios_instance = CACHED_EXPRESSIONS.get(expr_str)

         if not helios_instance:
            expr_node, member_node = n.named_children[0], n.named_children[1]
            helios_instance = self.ns_parser.infer_expr_type(expr_node)
            if not helios_instance:
               return
            member_str = member_node.text.decode('utf8')

         member = next(filter(lambda m: m.identifier == member_str, helios_instance.member_completions()), None)

      if not isinstance(member, HeliosFunction): # type: ignore
         return

      if len(member.parameters) == 0:
         # parameter-less functions don't need a signature
         return

      detail = cast(str, member.completion_information_self()['detail'])

      type_sig = detail.split(': ', 1)[1]
      documentation = cast(Union[str, MarkupContent], member.completion_information_self()['documentation'])

      logger.debug(type_sig)
      logger.debug(documentation)

      return (type_sig, documentation)

   def parse_struct_literal(self, node: Node) -> TypeSignature | None:
      struct_identifier = node.named_children[0].text.decode('utf8')
      struct = next(filter(lambda t: t.type_name == struct_identifier, self.ns_parser.global_types), None)

      def get_type_sig(struct_or_variant: Type[HeliosType], enum_type: None | Type[HeliosType] = None):
         type_sig = ''
         for f in struct_or_variant().fields:
            detail = f.completion_information_self()['detail'].replace('(field) ', '')
            if not type_sig:
               type_sig += detail 
            else:
               type_sig += ', ' + detail
         type_sig = '(' + type_sig + ')'
         if enum_type:
            v = struct_or_variant()
            type_sig += ' -> ' + f"{enum_type.type_name}::{v.identifier}"
         else:
            s = struct_or_variant
            type_sig += ' -> ' + s.type_name
         return type_sig

      if not struct:
         # check if it's an enum variant with fields (eg, Redeemer::Bid{42})
         l = list(map(lambda x: re.sub(r'\s+', '', x), struct_identifier.split('::')))
         enum = next(filter(lambda t: t.type_name == l[0], self.ns_parser.global_types), None)
         if not enum:
            return
         if enum.__name__ != "HeliosEnum":
            return # only works for user-defined enums
         enum_variants = [variant for variant in enum.path_completions() if isclass(variant)]
         if not enum_variants:
            return
         variant = [v for v in enum_variants if v.identifier == l[1]][0]
         if not variant().fields:
            return
         return get_type_sig(variant, enum)
         
      if struct.__name__ != "HeliosStruct":
         # attempted to instantiate an enum instance (eg, Redeemer{}) or non user-defined struct
         return

      return get_type_sig(struct)

   def infer_signature(self, tree: Tree, doc: Document, sig_params: SignatureHelpParams) -> SignatureHelp | None:
      position = Position(line=sig_params.position.line, character=sig_params.position.character - 1)
      node = self.node_from_position(tree, doc.lines[position.line][position.character], position)

      if not node:
         return

      if node.type == "call_expression":
         info = self.parse_call_expr(node)
         if not info:
            return
         if isinstance(info, tuple):
            type_sig, documentation = info 
         else:
            type_sig = info
            logger.debug(type_sig)
            documentation = None
      elif node.type == "struct_literal":
         type_sig = self.parse_struct_literal(node)
         if not type_sig:
            return
         documentation = None
      else:
         return None

      params_pattern = re.compile(r'\((.+)\)')
      params_str = re.findall(params_pattern, type_sig)[0]
      p = re.compile(r',(?![^(]*\))\s*')
      params = re.split(p, params_str)
      logger.debug(params)

      if len(params) == 1:
         active_index = 0
      else:
         active_index = self.active_index_from_node(node)
         logger.debug(active_index)

      sig_info = SignatureInformation(
         label=type_sig,
         documentation=documentation,
         parameters=[
            ParameterInformation(label=p)
            for p in params
         ],
         active_parameter=active_index
      )

      return SignatureHelp(signatures=[sig_info])
