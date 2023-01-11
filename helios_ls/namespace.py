from __future__ import annotations
import re
from inspect import isclass
from typing import List, Type, Tuple, Union, cast
from tree_sitter import Tree, Node
from .helios_types import (
   HeliosKeyword, StructNamespace, Element, HeliosType, HeliosFunction,
   print_function, error_function, keywords,
   factory_enum_variant_type, factory_enum_type, factory_struct_type,
   HeliosData, HeliosInt, HeliosBool, HeliosString, HeliosByteArray,
   factory_option_type, factory_list_type, factory_map_type,
   HeliosPubKeyHash, HeliosValidatorHash, HeliosMintingPolicyHash, HeliosDatumHash,
   HeliosDuration, HeliosTime, HeliosTimeRange, HeliosAssetClass, HeliosValue,
   HeliosCredential, HeliosStakingCredential, HeliosAddress,
   HeliosDCert, HeliosStakingPurpose, HeliosTxId, HeliosTxOutputId, HeliosOutputDatum,
   HeliosTxOutput, HeliosTxInput, HeliosScriptPurpose, HeliosTx, HeliosScriptContext
)
from .hlparser import HELIOS_LANGUAGE
from copy import deepcopy
from loguru import logger
from pprint import pformat


Line, Char = int, int
Position = Tuple[Line, Char]

BUILTIN_TYPES: List[Type[HeliosType]] = [
   HeliosData, HeliosInt, HeliosBool, HeliosString, HeliosByteArray,
   HeliosPubKeyHash, HeliosValidatorHash, HeliosMintingPolicyHash, HeliosDatumHash,
   HeliosDuration, HeliosTime, HeliosTimeRange, HeliosAssetClass, HeliosValue,
   HeliosCredential, HeliosStakingCredential, HeliosAddress,
   HeliosDCert, HeliosStakingPurpose, HeliosTxId, HeliosTxOutputId, HeliosOutputDatum,
   HeliosTxOutput, HeliosTxInput, HeliosScriptPurpose, HeliosTx, HeliosScriptContext
]

GLOBALS: List[HeliosFunction | HeliosKeyword] = [print_function, error_function, *keywords]

VALUE_EXPRESSIONS = [
   "literal_expression", "value_ref_expression", "value_path_expression",
   "unary_expression", "binary_expression", "parens_expression",
   "call_expression", "member_expression", "ifelse_expression", "switch_expression"
]

CACHED_EXPRESSIONS = {}
# Avoids having to re-compute entire value expressions. Otherwise hits a bottleneck in performance 
# after many chained call expressions, and auto-completion starts taking unacceptably long


class NamespaceParser:
   def __init__(self) -> None:
      self.global_types: List[Type[HeliosType]] = deepcopy(BUILTIN_TYPES)
      self.global_definitions: List[HeliosType | HeliosFunction] = []
      self.local_definitions: List[HeliosType | HeliosFunction] = []

   def parse_namespace(self, tree: Tree, position: Position) -> None:
      """Main method for updating global and local namespace."""
      self.update_global_namespace(tree, position)
      self.update_local_namespace(tree, position)

   def update_global_namespace(self, tree: Tree, position: Position) -> None:
      """Updates the global namespace for the document source: the global types, and the
      global definitions. Global types are those builtin in Helios and user-defined top-level
      struct & enum types. Global definitions include top-level constants and function statements.
      Constants can be (anon) functions themselves."""
      # Clear previous namespace
      self.global_types.clear()
      self.global_types = deepcopy(BUILTIN_TYPES)
      self.global_definitions.clear()

      query = HELIOS_LANGUAGE.query(
         """
            [
               (struct_statement) @definition.struct
               (enum_statement) @definition.enum
               (const_statement) @definition.constant
               (function_statement) @definition.function
            ]
         """
      )

      nodes = query.captures(tree.root_node)
      for node, _ in nodes:
         match node.type:
            case "struct_statement":
               name = self.name(node)
               struct_ns = self.parse_struct(node)
               self.global_types.append(factory_struct_type(name, struct_ns))
            case "enum_statement":
               name = self.name(node)
               enum_variants = self.parse_enum(node)
               self.global_types.append(factory_enum_type(name, enum_variants))
            case "const_statement":
               const = self.parse_const_or_assignment(node, element='constant')
               if not const:
                  continue
               self.global_definitions.append(const)
            case "function_statement":
               identifier = self.name(node)
               func = self.parse_function(node)
               if not func:
                  continue
               func.identifier = identifier
               func.element = 'function'
               self.global_definitions.append(func)
         if self.reached_destination_node(position, node):
            # no hoisting in Helios so we can stop parsing after reaching the cursor node
            break

   def update_local_namespace(self, tree: Tree, position: Position) -> None:
      """Updates the the local namespace for function and method blocks. Namespace includes
      asssignment expressions and function parameters (ie "variables")."""
      # Clear previous local namespace
      self.local_definitions.clear()

      line, _ = position
      top_level_definitions = tree.root_node.named_children

      current_node = None
      for node in top_level_definitions:
         if node.start_point[0] <= line <= node.end_point[0]:
            current_node = node
            break

      if not current_node:
         return

      logger.debug(current_node)

      def add_to_local_definitions(
         node_or_str: Node | str, helios_instance: HeliosType | HeliosFunction
      ) -> None:
         if isinstance(node_or_str, Node):
            identifier = self.name(node_or_str) # assignment_expression node
         else:
            identifier = node_or_str # string 
         helios_instance.identifier = identifier
         helios_instance.element = 'variable'
         helios_instance.documentation = None
         self.local_definitions.append(helios_instance)

      def local_ns(node: Node):
         """Parses the local namesapce. This comprises local (anon) function parameters, 
         and local assignment expressions. The solution below is not clever because it 
         does not take into account scope, and therefore you cannot use a variable name 
         multiple times inside a function/if-else block. Helios does have some limitations 
         on using multiple variable names, so it might not be too big of a deal for now."""
         query = HELIOS_LANGUAGE.query(
            """
               [
                  (literal_expression
                     (func_literal
                        (func_args)?)) @func
                  (assignment_expression) @assign
                  (switch_expression) @expr.switch
               ]
            """
         )
         nodes = query.captures(node)
         for n, _ in nodes:
            match n.type:
               case "assignment_expression":
                  expr = next(filter(lambda e: e.type in VALUE_EXPRESSIONS, n.named_children), None)
                  if not expr:
                     continue
                  helios_instance = cast(Union[HeliosType, HeliosFunction, None], self.infer_expr_type(expr))
                  if helios_instance:
                     add_to_local_definitions(n, helios_instance)
               case "literal_expression":
                  # func literal (anon func)
                  helios_function = cast(Union[HeliosFunction, None], self.infer_expr_type(n))
                  if helios_function:
                     self.local_definitions.extend(helios_function.parameters)
               case "switch_expression":
                  # switch case renames get completions
                  expr = next(filter(lambda e: e.type in VALUE_EXPRESSIONS, n.named_children), None)
                  if not expr:
                     continue
                  enum_instance = cast(Union[HeliosType, None], self.infer_expr_type(expr))
                  if not enum_instance:
                     continue
                  enum_variants = [variant for variant in enum_instance.path_completions() if isclass(variant)]
                  if not enum_variants:
                     continue
                  variant_renames = list(filter(lambda n: n.type == "variant_rename", n.named_children))
                  for vr in variant_renames:
                     name = vr.child_by_field_name('name').text.decode('utf8')
                     variant = vr.child_by_field_name('variant').text.decode('utf8')
                     for v in enum_variants:
                        variant_type_name: str = v.type_name.split('::')[-1]
                        if variant == variant_type_name:
                           add_to_local_definitions(name, v())

      match current_node.type:
         case "const_statement":
            expr = next(
               filter(lambda n: n.type in VALUE_EXPRESSIONS, current_node.named_children), None
            )
            if not expr:
               return
            local_ns(expr)
         case "struct_statement":
            for node in current_node.named_children:
               if not (node.start_point[0] <= line <= node.end_point[0]):
                  continue
               if node.type in ("method_statement", "function_statement"):
                  if node.type == "method_statement":
                     identifier = self.name(current_node)
                     helios_struct = next(filter(lambda t: t.type_name == identifier, self.global_types))
                     self.local_definitions.append(helios_struct(identifier="self", element="variable"))
                  helios_function = self.parse_function(node)
                  if not helios_function:
                     return
                  self.local_definitions.extend(helios_function.parameters)
                  block = next(filter(lambda n: n.type == 'block', node.named_children))
                  local_ns(block)
               elif node.type == "const_statement":
                  expr = next(
                     filter(lambda n: n.type in VALUE_EXPRESSIONS, node.named_children), None
                  )
                  if not expr:
                     return
                  local_ns(expr)
         case "function_statement" | "main_function_statement":
            helios_function = self.parse_function(current_node)
            if not helios_function:
               return
            self.local_definitions.extend(helios_function.parameters)
            block = next(filter(lambda n: n.type == 'block', current_node.named_children))
            local_ns(block)
         case _:
            local_ns(tree.root_node)

   def reached_destination_node(self, position: Position, node: Node) -> bool:
      """Checks if node's line position corresponds to current cursor position."""
      line, _ = position
      node_line_range = range(node.start_point[0], node.end_point[0]+1)
      return True if line in node_line_range else False

   def parse_struct(self, struct_node: Node) -> StructNamespace:
      struct_ns: StructNamespace = {
         "fields": [],
         "constants": [],
         "functions": [],
         "methods": []
      }

      query = HELIOS_LANGUAGE.query(
         """
         [
            (data_field) @definition.data_field
            (const_statement) @definition.constant
            (function_statement) @definition.function
            (method_statement) @definition.method
         ]
         """
      )

      nodes = query.captures(struct_node)
      for node, _ in nodes:
         match node.type:
            case "data_field":
               field = self.parse_field_or_func_param(node, element='field')
               if not field:
                  continue
               struct_ns["fields"].append(field)
            case "const_statement":
               const = self.parse_const_or_assignment(node, element='constant')
               if not const:
                  continue
               struct_ns["constants"].append(const)
            case "function_statement":
               identifier = self.name(node)
               func = self.parse_function(node)
               if not func:
                  continue
               func.identifier = identifier
               func.element = 'function'
               struct_ns["functions"].append(func)
            case "method_statement":
               identifier = self.name(node)
               method = self.parse_function(node)
               if not method: 
                  continue
               method.identifier = identifier
               method.element = 'method'
               struct_ns["methods"].append(method)

      return struct_ns

   def parse_enum(self, enum_node: Node) -> List[Type[HeliosEnumVariant]]:
      enum_name = self.name(enum_node)

      enum_variants: List[Type[HeliosEnumVariant]] = []

      query = HELIOS_LANGUAGE.query(
         """
         [
            (enum_variant) @definition.enum_variant
         ]
         """
      )

      nodes = query.captures(enum_node)
      for node, _ in nodes:
         variant = node.named_children
         identifier = variant[0].text.decode('utf8')
         if len(variant) > 1:
            fields = []
            for f in variant[1:]:
               field = self.parse_field_or_func_param(f, element='field')
               if field:
                  fields.append(field)
            enum_variants.append(factory_enum_variant_type(
               variant_name=identifier,
               variant_fields=fields,
               enum_name=f"{enum_name}::{identifier}"
            ))
         else:
            enum_variants.append(factory_enum_variant_type(
               variant_name=identifier,
               variant_fields=[],
               enum_name=f"{enum_name}::{identifier}"
            ))

      return enum_variants

   def parse_field_or_func_param(
      self, node: Node, element: Element
   ) -> HeliosType | HeliosFunction | None:
      """Struct fields and function parameters are parsed by their type signature."""
      assert element in ('field', 'variable') # function parameters are considered local "variables"

      identifier: str = self.name(node)
      type = node.child_by_field_name("type").children[0]

      match type.type:
         case "nonfunc_type":
            helios_type = self.parse_nonfunc_type(type)
            if helios_type:
               return helios_type(identifier=identifier, element=element)
         case "func_type":
            params_return_type = self.parse_func_type(type)
            if params_return_type:
               helios_params, helios_return_type = params_return_type
               return HeliosFunction(
                  identifier=identifier,
                  element=element,
                  parameters=helios_params,
                  return_type=helios_return_type,
                  documentation=None
               )

   def parse_const_or_assignment(
      self, node: Node, element: Element
   ) -> HeliosType | HeliosFunction | None:
      """In contrast to fields and function parameters, constants and assignments are parsed by
      their value expression (right hand side of the equals sign)."""
      assert element in ('constant', 'variable')

      identifier = self.name(node)

      expr = next(
         filter(lambda n: n.type in VALUE_EXPRESSIONS, node.named_children), None
      )

      if not expr:
         return

      helios_instance = cast(Union[HeliosType, HeliosFunction, None], self.infer_expr_type(expr))

      if helios_instance:
         helios_instance.identifier = identifier
         helios_instance.element = element
         return helios_instance

   def parse_function(self, node: Node) -> HeliosFunction | None:
      """Main method for parsing helios functions, methods and inline (anonymous) functions."""
      func_args = node.child_by_field_name('args')
      return_type = cast(Node, node.child_by_field_name('return_type'))

      def get_parameters() -> List[HeliosType | HeliosFunction] | None:
         if not func_args:
            return

         parameters = func_args.named_children

         helios_params: List[HeliosType | HeliosFunction] = []
         for param in parameters:
            p = param.named_children
            identifier = p[0].text.decode('utf8')
            type = p[1].children[0] # nonfunc_type/func_type node

            match type.type:
               case "nonfunc_type":
                  helios_type = self.parse_nonfunc_type(type)
                  if not helios_type:
                     return
                  helios_params.append(helios_type(identifier=identifier, element="variable"))
               case "func_type":
                  params_return_type = self.parse_func_type(type)
                  if not params_return_type:
                     return
                  _helios_params, _helios_return_type = params_return_type
                  helios_params.append(
                     HeliosFunction(
                        identifier=identifier,
                        element="variable",
                        parameters=_helios_params,
                        return_type=_helios_return_type,
                        documentation=None
                     )
                  )

         return helios_params

      if node.type == "main_function_statement":
         helios_params = get_parameters()
         helios_return_type = HeliosBool()
         return HeliosFunction(
            identifier="main",
            element="function",
            parameters=helios_params if helios_params else [],
            return_type=helios_return_type,
            documentation=None
         )
      else:
         helios_params = get_parameters()

         match return_type.children[0].type:
            case "nonfunc_type":
               helios_return_type = self.parse_nonfunc_type(return_type.children[0])
               if not helios_return_type:
                  return
               helios_return_type = helios_return_type()
            case "func_type":
               params_return_type = self.parse_func_type(return_type.children[0])
               if not params_return_type:
                  return
               _helios_params, _helios_return_type = params_return_type
               helios_return_type = HeliosFunction(
                  identifier=None,
                  element=None,
                  parameters=_helios_params,
                  return_type=_helios_return_type,
                  documentation=None
               )

         return HeliosFunction(
            identifier=None,
            element=None,
            parameters=helios_params if helios_params else [],
            return_type=helios_return_type, # type: ignore
            documentation=None
         )

   def name(self, node: Node) -> str:
      name = node.child_by_field_name("name").text.decode("utf8")
      return name

   def name_type_pair(self, node: Node) -> Tuple[str, str] | None:
      name = self.name(node)
      type = node.child_by_field_name("type")
      if not type:
         return
      type = type.text.decode("utf8")
      return (name, type)

   #--------------------------------------- Expression type parser ---------------------------------------#

   def infer_expr_type(self, node: Node) -> HeliosType | HeliosFunction | None:
      """Takes a value expression node and parses the expression using recursive descent approach,
      returning a HeliosType/HeliosFunction representation."""
      match node.type:
         case "member_expression":
            return self.parse_member_expression(node)
         case "value_path_expression":
            return self.parse_value_path_expression(node)
         case "value_ref_expression":
            return self.parse_value_ref_expression(node)
         case "literal_expression":
            return self.parse_literal_expression(node)
         case "call_expression":
            return self.parse_call_expression(node)
         case "parens_expression":
            return self.infer_expr_type(node.named_children[0])
         case "binary_expression":
            return self.parse_binary_expression(node)
         case "unary_expression":
            return self.parse_unary_expression(node)
         case "ifelse_expression" | "switch_expression":
            return self.parse_ifelse_switch_expression(node)

   def parse_member_expression(self, node: Node) -> HeliosType | HeliosFunction | None:
      node_children = node.named_children

      expr_node, identifier = node_children[0], node_children[1]

      expr_str = re.sub(r'\s+', '', expr_node.text.decode('utf8'))
      cached_helios_instance = CACHED_EXPRESSIONS.get(expr_str)

      if cached_helios_instance:
         local_definition = next(filter(lambda i: i.identifier == expr_str, self.local_definitions), None)
         if local_definition:
            if local_definition != cached_helios_instance:
               # value was changed, so clear the cache and use the new local definition instead
               logger.debug(pformat(CACHED_EXPRESSIONS))
               logger.debug(self.local_definitions)
               CACHED_EXPRESSIONS.clear()
               logger.debug("Cache cleared")
               helios_instance = local_definition
            else:
               helios_instance = cached_helios_instance
         else:
            helios_instance = cached_helios_instance
      else:
         helios_instance = cast(Union[HeliosType, HeliosFunction, None], self.infer_expr_type(expr_node))

         if not helios_instance:
            return

         # cache the hl instance
         CACHED_EXPRESSIONS[expr_str] = helios_instance

      if identifier.is_missing:
         return helios_instance

      identifier = identifier.text.decode('utf8') # identifier after the . in string fmt

      # get the member completions for the left expr
      member_completions = helios_instance.member_completions()

      if not member_completions:
         return

      member = next(filter(lambda m: m.identifier == identifier, member_completions), None)

      if not member:
         return helios_instance

      return deepcopy(member)

   def parse_call_expression(self, node: Node) -> HeliosType | HeliosFunction | None:
      match (n := node.named_children[0]).type:
         case "literal_expression" | "value_ref_expression" | "value_path_expression":
            func = self.infer_expr_type(n)
            if not isinstance(func, HeliosFunction):
               return # only functions can be called
            return deepcopy(func.return_type)
         case "member_expression":
            helios_instance = cast(HeliosType, self.infer_expr_type(n.named_children[0]))
            func = self.infer_expr_type(n)

            if not isinstance(func, HeliosFunction):
               return

            def get_callback():
               callback = self.infer_expr_type(node.named_children[1])
               if not isinstance(callback, HeliosFunction):
                  return
               if not isinstance(callback.return_type, HeliosType):
                  return
               return callback

            # Some functions like `map` and `fold` for lists have type parameters, and require special handling.
            match func_name := func.identifier:
               case 'fold' | 'fold_keys' | 'fold_values':
                  callback = get_callback()
                  if not callback:
                     return
                  callback_return_type = cast(Type[HeliosType], callback.return_type.__class__)
                  return callback_return_type()
               case 'map' | 'map_keys' | 'map_values':
                  callback = get_callback()
                  if not callback:
                     return
                  callback_return_type = cast(Type[HeliosType], callback.return_type.__class__)
                  if helios_instance.type_name.startswith('[]'):
                     return factory_list_type(item_type=callback_return_type)()
                  elif helios_instance.type_name.startswith('Map'):
                     if func_name == 'map_keys':
                        return factory_map_type(callback_return_type, deepcopy(helios_instance.v_type))()
                     elif func_name == 'map_values':
                        return factory_map_type(deepcopy(helios_instance.k_type), callback_return_type)()
               case _:
                  return deepcopy(func.return_type)

   def parse_value_path_expression(self, node: Node) -> HeliosType | HeliosFunction | None:
      node_children = node.named_children

      nonfunc_type, identifier = node_children[0], node_children[1]

      helios_type = self.parse_nonfunc_type(nonfunc_type)

      if not helios_type:
         return

      if identifier.is_missing:
         return helios_type()

      identifier = identifier.text.decode('utf8') # identifier after the :: in string fmt

      path_completions = helios_type.path_completions()

      member = next(filter(lambda m: m.identifier == identifier, path_completions), None)

      if isclass(member):
         # then member is a helios enum variant type
         enum_variant = member()

         if not enum_variant.fields and node.type == "path_type":
            return

         if enum_variant.fields and node.type == "value_path_expression":
            return

         return deepcopy(enum_variant)
      elif isinstance(member, (HeliosType, HeliosFunction)):
         return deepcopy(member)
      else:
         return helios_type()

   def parse_value_ref_expression(self, node: Node) -> HeliosType | HeliosFunction | None:
      ref = node.text.decode('utf8')

      helios_instances = self.global_definitions + self.local_definitions

      helios_reference = next(filter(lambda i: i.identifier == ref, helios_instances), None)

      if not helios_reference:
         return

      return deepcopy(helios_reference)

   def parse_literal_expression(self, node: Node) -> HeliosType | HeliosFunction | None:
      literal = node.named_children[0]
      match literal.type:
         case "int_literal":
            return HeliosInt()
         case "bool_literal":
            return HeliosBool()
         case "string_literal":
            return HeliosString()
         case "bytearray_literal":
            return HeliosByteArray()
         case "list_literal":
            list_type = self.parse_nonfunc_type(literal)
            if list_type:
               return list_type()
         case "map_literal":
            map_type = self.parse_nonfunc_type(literal)
            if map_type:
               return map_type()
         case "struct_literal":
            # Can be struct instance creation (eg, Datum{deadline: 100, addr: #12345}), which will have a 
            # struct_identifier field, OR a path type, ie accessing an enum variant with a field, in which 
            # case there will be a path_type node
            path_type = next(filter(lambda n: n.type == "path_type", literal.named_children), None)
            if path_type:
               s = cast(Union[HeliosType, HeliosFunction, None], self.parse_value_path_expression(path_type))
               return s

            struct_identifier = literal.child_by_field_name('struct_identifier')
            if struct_identifier:
               struct_identifier = struct_identifier.text.decode('utf8')
               helios_struct = next(filter(lambda t: t.type_name == struct_identifier, self.global_types), None)
               if helios_struct:
                  return helios_struct()
         case "func_literal":
            return self.parse_function(literal)

   def parse_nonfunc_type(self, node: Node) -> Type[HeliosType] | None:
      """Recursive function that takes a `nonfunc_type` node and returns a HeliosType class."""
      nonfunc_type = node.named_children[0]
      match nonfunc_type.type:
         case "int_type":
            return HeliosInt
         case "bool_type":
            return HeliosBool
         case "str_type":
            return HeliosString
         case "bytearray_type":
            return HeliosByteArray
         case "list_type":
            item_type = self.parse_nonfunc_type(nonfunc_type.named_children[0])
            if item_type:
               return factory_list_type(item_type)
         case "map_type":
            key_type = self.parse_nonfunc_type(nonfunc_type.named_children[0])
            value_type = self.parse_nonfunc_type(nonfunc_type.named_children[1])
            if key_type and value_type:
               return factory_map_type(key_type, value_type)
         case "option_type":
            opt_type = self.parse_nonfunc_type(nonfunc_type.named_children[0])
            if opt_type:
               return factory_option_type(opt_type)
         case "ref_type" | "identifier":
            ref = node.text.decode('utf8')
            return next(filter(lambda t: t.type_name == ref, self.global_types), None)
         case "path_type":
            # eg, x::y
            nf_type, identifier = nonfunc_type.named_children[0], nonfunc_type.named_children[1]
            n = self.parse_nonfunc_type(nf_type)
            if not n:
               return
            identifier = identifier.text.decode('utf8')
            path_completions = n.path_completions()
            member = cast(
               Union[Type[HeliosType], None],
               next(filter(lambda m: m.identifier == identifier, path_completions), None)
            )
            return member

   def parse_func_type(
      self, node: Node
   ) -> Tuple[List[HeliosType | HeliosFunction], HeliosType | HeliosFunction] | None:
      """Recursive function that takes a `func_type` node and returns a tuple of its
      parameter list and return type in HeliosType/HeliosFunction representation."""
      params = [n.children[0] for n in node.named_children[0:-1]] # list of nonfunc/func_type nodes
      return_type = node.named_children[-1].children[0]

      def get_type(n: Node) -> HeliosFunction | HeliosType | None:
         match n.type:
            case "nonfunc_type":
               helios_type = self.parse_nonfunc_type(n)
               if helios_type:
                  return helios_type()
            case "func_type":
               params_return_type = self.parse_func_type(n)
               if params_return_type:
                  _helios_params, _helios_return_type = params_return_type
                  return HeliosFunction(
                     identifier=None,
                     element=None,
                     parameters=_helios_params,
                     return_type=_helios_return_type,
                     documentation=None
                  )

      # params
      helios_params: List[HeliosType | HeliosFunction] = []
      for p in params:
         type = get_type(p)
         if not type:
            return
         helios_params.append(type)

      # return type
      helios_return_type = get_type(return_type)

      if not helios_return_type:
         return

      return (helios_params, helios_return_type)

   def parse_binary_expression(self, node: Node) -> HeliosType | None:
      left_expr, symbol, right_expr = node.children[0], node.children[1], node.children[2]

      left_helios_instance = cast(Union[HeliosType, None], self.infer_expr_type(left_expr))
      right_helios_instance = cast(Union[HeliosType, None], self.infer_expr_type(right_expr))
      symbol = symbol.text.decode('utf8')

      if not left_helios_instance or not right_helios_instance:
         return

      match (left_helios_instance.type_name, right_helios_instance.type_name):
         case ("Duration", "Duration"):
            if symbol in ['==', '!=', ">=", ">", "<=", "<"]:
               return HeliosBool()
            elif symbol in ('+', '-', '%'):
               return HeliosDuration()
            elif symbol == '/':
               return HeliosInt()
         case ("Duration", "Int"):
            if symbol in ('*', '/'):
               return HeliosDuration()
         case ("Int", "Duration"):
            if symbol == '*':
               return HeliosDuration()
         case ("Time", "Time"):
            if symbol in ['==', '!=', ">=", ">", "<=", "<"]:
               return HeliosBool()
            elif symbol == '-':
               return HeliosDuration()
         case ("Time", "Duration"):
            if symbol in ('+', '-'):
               return HeliosTime()
         case ("Duration", "Time"):
            if symbol == '+':
               return HeliosTime()
         case ("Value", "Value"):
            if symbol in ['==', '!=', ">=", ">", "<=", "<"]:
               return HeliosBool()
            elif symbol in ('+', '-'):
               return HeliosValue()
         case ("Value", "Int"):
            if symbol in ('*', '/'):
               return HeliosValue()
         case ("Int", "Value"):
            if symbol == '*':
               return HeliosValue()
         case _:
            # default
            if type(left_helios_instance) != type(right_helios_instance):
               return
            if symbol in left_helios_instance.operators: # left or right doesn't matter because they're of the same type
               if symbol in ['==', '!=', ">=", ">", "<=", "<"]:
                  return HeliosBool()
               return left_helios_instance

   def parse_unary_expression(self, node: Node) -> HeliosType | None:
      node_children = node.children

      symbol, expr = node_children[0], node_children[1]

      helios_instance = cast(Union[HeliosType, None], self.infer_expr_type(expr))

      if not helios_instance:
         return

      if symbol.text.decode('utf8') in helios_instance.unary:
         return helios_instance

   def parse_ifelse_switch_expression(self, node: Node) -> HeliosType | HeliosFunction | None:
      """Takes an ifelse/switch expression node and checks the return types for each block. If the 
      block return types are not the same, it will return None, HeliosType/HeliosFunction otherwise."""
      block_nodes = list(filter(lambda n: n.type == 'block', node.named_children))

      value_expressions = []

      for block in block_nodes:
         v = next(filter(lambda n: n.type in VALUE_EXPRESSIONS, block.named_children), None) # return value node
         if v:
            helios_instance = cast(Union[HeliosType, HeliosFunction, None], self.infer_expr_type(v))
            value_expressions.append(helios_instance)

      if len(value_expressions) != len(block_nodes):
         return

      helios_instance = value_expressions[0] # choose the first one - doesn't matter
      type = helios_instance.__class__
      is_same_type = all(i.__class__ == type for i in value_expressions)

      if is_same_type and helios_instance is not None:
         return helios_instance
