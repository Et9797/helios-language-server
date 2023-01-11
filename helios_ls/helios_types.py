"""Python representation of Helios types."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Dict, TypedDict, Literal, Type
from dataclasses import dataclass, field
from pygls.lsp.types import CompletionItemKind
from pygls.lsp.types.basic_structures import MarkupContent, MarkupKind


####### Type aliases and declarations
CompletionInformation = Dict[str, str | MarkupContent | CompletionItemKind | None]
Element = Literal['variable', 'constant', 'field', 'function', 'method', 'property', 'enum variant', 'keyword']
ContainerKind = Literal['struct', 'enum']
element_to_itemkind = {
   'variable': CompletionItemKind.Variable,
   'constant': CompletionItemKind.Constant,
   'field': CompletionItemKind.Field,
   'function': CompletionItemKind.Function,
   'method': CompletionItemKind.Method,
   'property': CompletionItemKind.Property,
   'enum variant': CompletionItemKind.EnumMember,
   'keyword': CompletionItemKind.Keyword
}


@dataclass
class HeliosKeyword:
   identifier: str
   element: str = field(init=False, repr=False, default='keyword')

   def completion_information_self(self) -> CompletionInformation:
      return {
         "label": f"{self.identifier}",
         "kind": element_to_itemkind[self.element],
         "detail": f"({self.element}) {self.identifier}",
      }


keywords = [
   HeliosKeyword(kw)
   for kw in ['const', 'func', 'struct', 'enum', 'if', 'else', 'Option']
]


switch_kw = HeliosKeyword('switch') # separate because don't want globally available


####### Helios functions
@dataclass
class HeliosFunction:
   """Class for top level functions and anonymous functions. Doesn't need to inherit from
   HeliosType base class (is its own entity)."""
   identifier: str | None
   element: Element | None
   parameters: List[HeliosType | HeliosFunction] # note: can be empty list too, ie no parameters: ()
   return_type: HeliosType | HeliosFunction | None
   documentation: str | MarkupContent | None = field(init=True, default=None)

   def member_completions(self):
      if self.return_type:
         return self.return_type.member_completions()

   def _get_function_type_sig(self, func: HeliosFunction) -> str:
      """Recursive helper function for extracting the type signature of the function.
      Parameters and return type can be HeliosFunctions themselves (ie take or return
      another function).
      """
      if not func.return_type:
         return ''

      params = []
      for param in func.parameters:
         if isinstance(param, HeliosType):
            if func is self and bool(param.identifier) is True and param.element == 'variable':
               params.append(f"{param.identifier}: {param.type_name}")
            else:
               params.append(f"{param.type_name}")
         elif isinstance(param, HeliosFunction):
            if func is self and bool(param.identifier) is True and param.element == 'variable':
               params.append(f"{param.identifier}: {self._get_function_type_sig(param)}")
            else:
               params.append(self._get_function_type_sig(param))

      params_str_format = '(' + ', '.join(params) + ')'

      if isinstance(func.return_type, HeliosType):
         return_type_str_format = func.return_type.type_name
      elif isinstance(func.return_type, HeliosFunction):
         return_type_str_format = self._get_function_type_sig(func.return_type)

      return f"{params_str_format} -> {return_type_str_format}" # type: ignore

   def completion_information_self(self) -> CompletionInformation:
      assert bool(self.identifier) is True and self.element is not None

      func_type_sig = self._get_function_type_sig(self)

      return {
         "label": f"{self.identifier}",
         "kind": element_to_itemkind[self.element],
         "detail": f"({self.element}) {self.identifier}{': ' + func_type_sig if func_type_sig else ''}",
         "documentation": self.documentation
      }


print_function = HeliosFunction(
   identifier='print',
   element='function',
   parameters=[],
   return_type=None,
   documentation=MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         'Prints a string expression. Expression has to be of `String` type, because '
         'there is no implicit type conversion in Helios.'
      )
   )
)

error_function = HeliosFunction(
   identifier='error',
   element='function',
   parameters=[],
   return_type=None,
   documentation='For throwing errors. Can only be used inside if-else/switch blocks.'
)


####### Helios base type class. All types inherit from this class
@dataclass(kw_only=True)
class HeliosType(ABC):
   """This base class is inherited by all Helios builtin types and user-defined
   types (structs & enums)."""
   identifier: str | None = field(init=True, default=None) # name of the instance defined in Helios
   element: Element | None = field(init=True, default=None)
   documentation: str | MarkupContent | None = field(init=True, default=None)
   fields: List[HeliosType | HeliosFunction] = field(init=False, repr=False, default_factory=list) # for enum variants & struct
   type_name: str = field(init=False, repr=False, default='')
   # name of the (user-defined) Helios type in string repr. Default name except for dynamic types (eg, structs/enums)
   container_kind: ContainerKind = field(init=False, repr=False, default='struct')

   @property
   def _innate_operators(self):
      return ["==", "!="]

   @property
   def _serialize(self) -> HeliosFunction:
      return HeliosFunction(
         identifier="serialize",
         element="method",
         parameters=[],
         return_type=HeliosByteArray(),
         documentation=MarkupContent(
            kind=MarkupKind.Markdown,
            value="Returns a `CBOR` hex-encoded byte array."
         )

      )

   @classmethod
   def _from_data(cls) -> HeliosFunction:
      return HeliosFunction(
         identifier="from_data",
         element="function",
         parameters=[HeliosData(identifier="data", element="variable", documentation=None)],
         return_type=cls(),
         documentation="Convert typeless data to typed representation."
      )

   @property
   def operators(self) -> List[str]:
      return self._innate_operators

   @property
   def unary(self) -> List[str]:
      return []

   @abstractmethod
   def member_completions(self) -> List[HeliosType | HeliosFunction]:
      "Implementation in derived type class"

   @classmethod
   @abstractmethod
   def path_completions(cls) -> List[HeliosType | HeliosFunction | Type[HeliosType]]:
      "Implementation in derived type class"

   def completion_information_self(self) -> CompletionInformation:
      assert bool(self.identifier) is True and self.element is not None
      return {
         "label": f"{self.identifier}",
         "kind": element_to_itemkind[self.element],
         "detail": f"({self.element}) {self.identifier}: {self.type_name}",
         "documentation": self.documentation
      }

   @classmethod
   def completion_information_type(cls) -> CompletionInformation:
      return {
         "label": f"{cls.type_name}",
         "kind": (
            CompletionItemKind.Struct
            if cls.container_kind == 'struct'
            else CompletionItemKind.Enum
         ),
         "detail": f"({cls.container_kind}) {cls.type_name}",
         "documentation": cls.documentation
      }


@dataclass
class HeliosTypeParameter(HeliosType):
   """Placeholder type class for type parameters, eg required for the fold and map methods of lists."""
   type_name: str = field(init=False, repr=True, default='T')

   def member_completions(self):
      raise NotImplementedError

   @classmethod
   def path_completions(cls):
      raise NotImplementedError


####### Helios struct
class StructNamespace(TypedDict):
   fields: List[HeliosType | HeliosFunction]
   constants: List[HeliosType | HeliosFunction]
   functions: List[HeliosFunction]
   methods: List[HeliosFunction]


def factory_struct_type(struct_name: str, struct_ns: StructNamespace):
   @dataclass
   class HeliosStruct(HeliosType):
      type_name: str = field(init=False, repr=True, default=struct_name)
      fields: List[HeliosType | HeliosFunction] = field(init=False, repr=False, default_factory=lambda: struct_ns["fields"])

      def member_completions(self) -> List[HeliosType | HeliosFunction]:
         return [self._serialize, *struct_ns["fields"], *struct_ns["methods"]]

      @classmethod
      def path_completions(cls) -> List[HeliosType | HeliosFunction]:
         return [cls._from_data(), *struct_ns["constants"], *struct_ns["functions"]]

   return HeliosStruct


####### Helios enum
Field = HeliosType | HeliosFunction


def factory_enum_variant_type(
   variant_name: str, variant_fields: List[Field], enum_name: str, has_from_data: bool = False
):
   @dataclass
   class HeliosEnumVariant(HeliosType):
      identifier: str = variant_name
      element: str = 'enum variant'
      type_name: str = field(init=False, repr=True, default=enum_name)
      fields: List[HeliosType | HeliosFunction] = field(init=False, repr=True, default_factory=lambda: variant_fields)

      def member_completions(self) -> List[HeliosType | HeliosFunction]:
         for f in self.fields:
            assert bool(f.identifier) is True and f.element in ('field', 'property', 'method')
         return [self._serialize, *self.fields]

      @classmethod
      def path_completions(cls):
         if has_from_data:
            return [cls._from_data()]
         else:
            return []

   return HeliosEnumVariant


def factory_enum_type(enum_name: str, enum_variants: List[Type[HeliosEnumVariant]]): # type: ignore
   @dataclass
   class HeliosEnum(HeliosType):
      type_name: str = field(init=False, repr=True, default=enum_name)
      container_kind: str = field(init=False, repr=False, default='enum')

      def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
         return [self._serialize, switch_kw]

      @classmethod
      def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
         return [cls._from_data(), *enum_variants] # type: ignore

   return HeliosEnum


####### Helios builtin types #######
@dataclass
class HeliosData(HeliosType):
   type_name: str = field(init=False, repr=False, default='Data')
   container_kind: str = field(init=False, repr=False, default='enum')

   def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
      return [self._serialize, switch_kw]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [cls._from_data()]


####### Helios primitives
@dataclass
class HeliosInt(HeliosType):
   type_name: str = field(init=False, repr=False, default='Int')

   @property
   def operators(self) -> List[str]:
      return ["-", "+", "*", "/", "%", ">=", ">", "<=", "<"] + self._innate_operators

   @property
   def unary(self) -> List[str]:
      return ["-", "+"]

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="to_bool",
            element="method",
            parameters=[],
            return_type=HeliosBool(),
            documentation="Convert to boolean."
         ),
         HeliosFunction(
            identifier="to_hex",
            element="method",
            parameters=[],
            return_type=HeliosInt(),
            documentation="Convert to hexadecimal representation."
         ),
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="parse",
            element="function",
            parameters=[HeliosString(identifier="s", element="variable", documentation=None)],
            return_type=cls(),
            documentation="Cast a string to an integer."
         )
      ]


@dataclass
class HeliosBool(HeliosType):
   type_name: str = field(init=False, repr=False, default='Bool')

   @property
   def operators(self):
      return ["&&", "||"] + self._innate_operators

   @property
   def unary(self):
      return ["!"]

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="to_int",
            element="method",
            parameters=[],
            return_type=HeliosInt(),
            documentation="Convert to integer."
         ),
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         ),

      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="and",
            element="function",
            parameters=[
               HeliosFunction(
                  identifier="fn_a",
                  element="variable",
                  parameters=[],
                  return_type=HeliosBool(),
                  documentation=None
               ),
               HeliosFunction(
                  identifier="fn_b",
                  element="variable",
                  parameters=[],
                  return_type=HeliosBool(),
                  documentation=None
               )
            ],
            return_type=cls(),
            documentation=None
         ),
         HeliosFunction(
            identifier="or",
            element="function",
            parameters=[
               HeliosFunction(
                  identifier="fn_a",
                  element="variable",
                  parameters=[],
                  return_type=HeliosBool(),
                  documentation=None
               ),
               HeliosFunction(
                  identifier="fn_b",
                  element="variable",
                  parameters=[],
                  return_type=HeliosBool(),
                  documentation=None
               )
            ],
            return_type=cls(),
            documentation=None
         )
      ]


@dataclass
class HeliosString(HeliosType):
   type_name: str = field(init=False, repr=False, default='String')

   @property
   def operators(self):
      return ["+"] + self._innate_operators

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="starts_with",
            element="method",
            parameters=[HeliosString(identifier="prefix", element="variable", documentation=None)],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if the string starts with the specified prefix, "
                  "`false` otherwise."
               )
            )
         ),
         HeliosFunction(
            identifier="ends_with",
            element="method",
            parameters=[HeliosString(identifier="suffix", element="variable", documentation=None)],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if the string ends with the specified suffix, "
                  "`false` otherwise."
               )
            )
         ),
         HeliosFunction(
            identifier="encode_utf8",
            element="method",
            parameters=[],
            return_type=HeliosByteArray(),
            documentation=None
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [cls._from_data()]


@dataclass
class HeliosByteArray(HeliosType):
   type_name: str = field(init=False, repr=False, default='ByteArray')

   @property
   def operators(self):
      return ["+"] + self._innate_operators

   def member_completions(self) -> List[HeliosType | HeliosFunction]:
      return [
         self._serialize,
         HeliosInt(
            identifier="length",
            element="property",
            documentation="Length of the byte array."
         ),
         HeliosFunction(
            identifier="slice",
            element="method",
            parameters=[
               HeliosInt(identifier="begin", element="variable", documentation=None),
               HeliosInt(identifier="end", element="variable", documentation=None)
            ],
            return_type=HeliosByteArray(),
            documentation=(
               "Slices the byte array from begin to end index. The begin index is "
               "inclusive, while the end index is exclusive."
            )
         ),
         HeliosFunction(
            identifier="starts_with",
            element="method",
            parameters=[HeliosByteArray(identifier="prefix", element="variable", documentation=None)],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if the byte array starts with the specified prefix, "
                  "`false` otherwise."
               )
            )
         ),
         HeliosFunction(
            identifier="ends_with",
            element="method",
            parameters=[HeliosByteArray(identifier="suffix", element="variable", documentation=None)],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if the byte array ends with the specified suffix, "
                  "`false` otherwise."
               )
            )
         ),
         HeliosFunction(
            identifier="decode_utf8",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="UTF-8 decode to string format."
         ),
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         ),
         *[
            HeliosFunction(
               identifier=h,
               element="method",
               parameters=[],
               return_type=HeliosByteArray(),
               documentation=f"Returns the {h} hash of the byte array. The result is 32 bytes long."
            )
            for h in ['sha2', 'sha3', 'blake2b']
         ]
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [cls._from_data()]


####### Helios container types: List, Map & Option
####### These are dynamic types like Struct and Enum, therefore requiring a factory
def factory_option_type(opt_type: Type[HeliosType]):
   @dataclass
   class HeliosOption(HeliosType):
      type_name: str = field(init=False, repr=True, default=f'Option[{opt_type.type_name}]')
      container_kind: str = field(init=False, repr=False, default='enum')

      def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
         return [
            self._serialize,
            HeliosFunction(
               identifier="unwrap",
               element="method",
               parameters=[],
               return_type=opt_type(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns the value wrapped by `Some`. Throws an error if `None`."
                  )
               )
            ),
            switch_kw
         ]

      @classmethod
      def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
         return [
            cls._from_data(),
            factory_enum_variant_type(
               variant_name='Some',
               variant_fields=[opt_type(identifier='some', element='property')], # field/property is synonymous here
               enum_name=f"{cls.type_name}::Some"
            ),
            factory_enum_variant_type(
               variant_name='None', variant_fields=[], enum_name=f"{cls.type_name}::None"
            )
         ]

   return HeliosOption


def factory_list_type(item_type: Type[HeliosType]):
   @dataclass
   class HeliosList(HeliosType):
      type_name: str = field(init=False, repr=True, default=f'[]{item_type.type_name}')

      @property
      def operators(self) -> List[str]:
         return ['+'] + self._innate_operators

      def member_completions(self) -> List[HeliosType | HeliosFunction]:
         return [
            self._serialize,
            HeliosInt(
               identifier="length",
               element="property",
               documentation="Returns the length of the list."
            ),
            item_type(
               identifier="head",
               element="property",
               documentation="Returns the first item in the list. Throws an error if the list is empty."
            ),
            self.__class__(
               identifier="tail",
               element="property",
               documentation="Returns the list items following the first item. Throws an error if the list is empty."
            ),
            HeliosFunction(
               identifier="is_empty",
               element="method",
               parameters=[],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value="Returns `true` if the list is empty."
               )
            ),
            HeliosFunction(
               identifier="get",
               element="method",
               parameters=[HeliosInt(identifier="index", element="variable")],
               return_type=item_type(),
               documentation=(
                  "Returns the item at the given position in the list (0-based index). "
                  "Throws an error if the index is out of range."
               )
            ),
            HeliosFunction(
               identifier="prepend",
               element="method",
               parameters=[item_type(identifier="item", element="variable")],
               return_type=self.__class__(),
               documentation="Creates a new list by prepending an item to the old list."
            ),
            HeliosFunction(
               identifier="any",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[item_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if any item in the list satisfies the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="all",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[item_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if all items in the list satisfy the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="find",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[item_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=item_type(),
               documentation=(
                  "Returns the first item in the list that satisfies the predicate. "
                  "Throws an error if no item satisfies the predicate."
               )
            ),
            HeliosFunction(
               identifier="find_safe",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[item_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=factory_option_type(item_type)(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns the first item in the list that satisfies the predicate, wrapped in an `Option`. "
                     f"Returns `Option`[`{item_type.type_name}`]::`None` if no items match the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="filter",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[item_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=self.__class__(),
               documentation="Returns a list of all the items in the old list that satisfy the predicate."
            ),
            HeliosFunction(
               identifier="fold",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="reducer",
                     element="variable",
                     parameters=[HeliosTypeParameter(), item_type()],
                     return_type=HeliosTypeParameter(),
                     documentation=None
                  ),
                  HeliosTypeParameter(
                     identifier="accumulator_init",
                     element="variable",
                     documentation=None
                  )
               ],
               return_type=HeliosTypeParameter(),
               documentation=(
                  "Folds a list into a single value by continuously applying the "
                  "binary function to the items of the list."
               )
            ),
            HeliosFunction(
               identifier="map",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="callback",
                     element="variable",
                     parameters=[item_type()],
                     return_type=HeliosTypeParameter(),
                     documentation=None
                  )
               ],
               return_type=factory_list_type(HeliosTypeParameter)(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Transforms each item of the list. The resulting list item type will be"
                     " of type `T`. Note: `T` can only be a non-function type. "
                     "In other words, you cannot have a list of functions."
                  )
               )
            )
         ]

      @classmethod
      def path_completions(cls) -> List[HeliosFunction]:
         return [
            cls._from_data(),
            HeliosFunction(
               identifier="new",
               element="function",
               parameters=[
                  HeliosInt(identifier="n", element="variable"),
                  HeliosFunction(
                     identifier="fn",
                     element="variable",
                     parameters=[HeliosInt()],
                     return_type=item_type(),
                     documentation=None
                  )
               ],
               return_type=cls(),
               documentation=(
                  "Creates a new list of length n, where every contained item is "
                  "determined by callback fn. The callback takes the index (Int) "
                  "as a parameter, and returns an instance of the list's item type."
               )
            ),
            HeliosFunction(
               identifier="new_const",
               element="function",
               parameters=[
                  HeliosInt(identifier="n", element="variable", documentation=None),
                  item_type(identifier="item", element="variable", documentation=None)
               ],
               return_type=cls(),
               documentation="Creates a new list of length n, where every contained item is the same."
            )
         ]

   return HeliosList


def factory_map_type(key_type: Type[HeliosType], value_type: Type[HeliosType]):
   @dataclass
   class HeliosMap(HeliosType):
      k_type = key_type
      v_type = value_type
      type_name: str = field(init=False, repr=True, default=f'Map[{key_type.type_name}]{value_type.type_name}')

      @property
      def operators(self) -> List[str]:
         return ['+'] + self._innate_operators

      def member_completions(self) -> List[HeliosType | HeliosFunction]:
         return [
            self._serialize,
            HeliosInt(
               identifier="length",
               element="property",
               documentation="Returns the number of items in the map."
            ),
            HeliosFunction(
               identifier="is_empty",
               element="method",
               parameters=[],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if the map is empty."
                  )
               )
            ),
            HeliosFunction(
               identifier="get",
               element="method",
               parameters=[key_type(identifier="key", element="variable")],
               return_type=value_type(),
               documentation=(
                  "Returns the value of the first entry in the map that matches the given key. "
                  "Throws an error of the key isn't found."
               )
            ),
            HeliosFunction(
               identifier="get_safe",
               element="method",
               parameters=[key_type(identifier="key", element="variable")],
               return_type=factory_option_type(value_type)(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns the value of the first entry in the map that matches the given key, "
                     f"wrapped in an `Option`. Returns `Option[{value_type.type_name}]`::`None` if the key "
                     "is not found."
                  )
               )
            ),
            HeliosFunction(
               identifier="all",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[key_type(), value_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if all map items satisfy the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="all_keys",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[key_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if all map keys satisfy the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="all_values",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[value_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if all map values satisfy the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="any",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[key_type(), value_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if any map item satisfies the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="any_key",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[key_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if any map key satisfies the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="any_value",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[value_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=HeliosBool(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Returns `true` if any map value satisfies the predicate."
                  )
               )
            ),
            HeliosFunction(
               identifier="filter",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[key_type(), value_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=self.__class__(),
               documentation="Returns a map with items from the old map that satisfy the predicate."
            ),
            HeliosFunction(
               identifier="filter_by_key",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[key_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=self.__class__(),
               documentation="Returns a map with items from the old map that satisfy the predicate."
            ),
            HeliosFunction(
               identifier="filter_by_value",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="predicate",
                     element="variable",
                     parameters=[value_type()],
                     return_type=HeliosBool(),
                     documentation=None
                  )
               ],
               return_type=self.__class__(),
               documentation="Returns a map with items from the old map that satisfy the predicate."
            ),
            HeliosFunction(
               identifier="fold",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="reducer",
                     element="variable",
                     parameters=[HeliosTypeParameter(), key_type(), value_type()],
                     return_type=HeliosTypeParameter(),
                     documentation=None
                  ),
                  HeliosTypeParameter(
                     identifier="accumulator_init",
                     element="variable",
                     documentation=None
                  )
               ],
               return_type=HeliosTypeParameter(),
               documentation=(
                  "Folds a map into a single value by continuously applying the "
                  "callback to the items of the map."
               )
            ),
            HeliosFunction(
               identifier="fold_keys",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="reducer",
                     element="variable",
                     parameters=[HeliosTypeParameter(), key_type()],
                     return_type=HeliosTypeParameter(),
                     documentation=None
                  ),
                  HeliosTypeParameter(
                     identifier="accumulator_init",
                     element="variable",
                     documentation=None
                  )
               ],
               return_type=HeliosTypeParameter(),
               documentation=(
                  "Folds a map into a single value by continuously applying the "
                  "callback to the keys of the map."
               )
            ),
            HeliosFunction(
               identifier="fold_values",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="reducer",
                     element="variable",
                     parameters=[HeliosTypeParameter(), value_type()],
                     return_type=HeliosTypeParameter(),
                     documentation=None
                  ),
                  HeliosTypeParameter(
                     identifier="accumulator_init",
                     element="variable",
                     documentation=None
                  )
               ],
               return_type=HeliosTypeParameter(),
               documentation=(
                  "Folds a map into a single value by continuously applying the "
                  "callback to the values of the map."
               )
            ),
            HeliosFunction(
               identifier="map_keys",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="callback",
                     element="variable",
                     parameters=[key_type()],
                     return_type=HeliosTypeParameter(),
                     documentation=None
                  )
               ],
               return_type=factory_map_type(HeliosTypeParameter, value_type)(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Creates a new map by transforming the map keys. The map values remain the same. "
                     "The resulting key type will be of type `T`. Note: `T` can only be a non-function type."
                  )
               )
            ),
            HeliosFunction(
               identifier="map_values",
               element="method",
               parameters=[
                  HeliosFunction(
                     identifier="callback",
                     element="variable",
                     parameters=[value_type()],
                     return_type=HeliosTypeParameter(),
                     documentation=None
                  )
               ],
               return_type=factory_map_type(key_type, HeliosTypeParameter)(),
               documentation=MarkupContent(
                  kind=MarkupKind.Markdown,
                  value=(
                     "Creates a new map by transforming the map values. The map keys remain the same. "
                     "The resulting value type will be of type `T`. Note: `T` can only be a non-function type."
                  )
               )
            )
         ]

      @classmethod
      def path_completions(cls) -> List[HeliosFunction]:
         return [cls._from_data()]

   return HeliosMap


####### Hash types
@dataclass
class HeliosPubKeyHash(HeliosType):
   type_name: str = field(init=False, repr=False, default='PubKeyHash')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "This is a type-safe wrapper around `ByteArray` that represents the hash of a public key. "
         "The first part of a regular payment address is a `PubKeyHash`.\n"
         "Example instantiation:\n"
         "\tpkh: `PubKeyHash` = `PubKeyHash`::`new`(#...); ..."
      )
   )

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[HeliosByteArray(identifier="bytes", element="variable")],
            return_type=cls(documentation=None),
            documentation=None
         )
      ]


@dataclass
class HeliosValidatorHash(HeliosType):
   type_name: str = field(init=False, repr=False, default='ValidatorHash')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "This is a type-safe wrapper around `ByteArray` that represents the hash of a validator script. "
         "The first part of a script address is formed by a `ValidatorHash`.\n"
         "Example instantiation:\n"
         "\tvh: `ValidatorHash` = `ValidatorHash`::`new`(#...); ..."
      )
   )

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[HeliosByteArray(identifier="bytes", element="variable")],
            return_type=cls(documentation=None),
            documentation=None
         )
      ]


@dataclass
class HeliosMintingPolicyHash(HeliosType):
   type_name: str = field(init=False, repr=False, default='MintingPolicyHash')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "This is a type-safe wrapper around `ByteArray` that represents the hash of a minting policy script.\n"
         "Example instantiation:\n"
         "\tmph: `MintingPolicyHash` = `MintingPolicyHash`::`new`(#...); ..."
      )
   )

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[HeliosByteArray(identifier="bytes", element="variable")],
            return_type=cls(documentation=None),
            documentation=None
         )
      ]


@dataclass
class HeliosDatumHash(HeliosType):
   type_name: str = field(init=False, repr=False, default='DatumHash')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "This is a type-safe wrapper around `ByteArray` that represents the hash of datum.\n"
         "Example instantiation:\n"
         "\tdh: `DatumHash` = `DatumHash`::`new`(#...); ..."
      )
   )

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[HeliosByteArray(identifier="bytes", element="variable")],
            return_type=cls(documentation=None),
            documentation=None
         )
      ]


####### Time types
@dataclass
class HeliosDuration(HeliosType):
   type_name: str = field(init=False, repr=False, default='Duration')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "The difference of two `Time` values is a `Duration` value. Only a `Duration` can be "
         "added to a `Time` (two `Time` values can't be added)."
      )
   )

   def operators(self) -> List[str]:
      return [">=", ">", "<=", "<", '+', '-', '%', '*', '/'] + self._innate_operators # special case in parse_binary_expression

   def member_completions(self) -> List[HeliosFunction]:
      return [self._serialize]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[HeliosInt(identifier="milliseconds", element="variable")],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Instantiate a `Duration` from a number of milliseconds."
               )
            )
         )
      ]


@dataclass
class HeliosTime(HeliosType):
   type_name: str = field(init=False, repr=False, default='Time')
   documentation = "Represents POSIX time in milliseconds (time since 1970/01/01 00:00:00 UTC)."

   def operators(self) -> List[str]:
      return [">=", ">", "<=", "<", '+', '-'] + self._innate_operators # special case in parse_binary_expression

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="show",
            element="method",
            parameters=[],
            return_type=HeliosString(),
            documentation="Cast to string."
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[HeliosInt(identifier="posix_time_ms", element="variable")],
            return_type=cls(documentation=None),
            documentation=None
         )
      ]


@dataclass
class HeliosTimeRange(HeliosType):
   type_name: str = field(init=False, repr=False, default='TimeRange')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "This represents a range of time using a pair of `Time` values, or open ends."
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosType]:
      return [
         self._serialize,
         HeliosTime(
            identifier="start",
            element="property",
            documentation=None
         ),
         HeliosTime(
            identifier="end",
            element="property",
            documentation=None
         ),
         HeliosFunction(
            identifier="contains",
            element="method",
            parameters=[HeliosTime(identifier="time", element="variable")],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if a `TimeRange` contains the given time."
               )
            )
         ),
         HeliosFunction(
            identifier="is_before",
            element="method",
            parameters=[HeliosTime(identifier="time", element="variable")],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if the end of a `TimeRange` is before the given time. Always "
                  "returns `false` if the end of the `TimeRange` is positive infinity."
               )
            )
         ),
         HeliosFunction(
            identifier="is_after",
            element="method",
            parameters=[HeliosTime(identifier="time", element="variable")],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if the start of a `TimeRange` is after the given time. Always "
                  "returns `false` if the start of the `TimeRange` is negative infinity."
               )
            )
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | HeliosType]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               HeliosTime(identifier="start", element="variable"),
               HeliosTime(identifier="end", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns a `TimeRange` that contains all `Time` values between start and end."
               )
            )
         ),
         HeliosFunction(
            identifier="to",
            element="function",
            parameters=[HeliosTime(identifier="end", element="variable")],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns a `TimeRange` that contains all `Time` values until end."
               )
            )
         ),
         HeliosFunction(
            identifier="from",
            element="function",
            parameters=[HeliosTime(identifier="start", element="variable")],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns a `TimeRange` that contains all `Time` values from start onwards."
               )
            )
         ),
         cls(
            identifier="ALWAYS",
            element="constant",
            documentation=None
         ),
         cls(
            identifier="NEVER",
            element="constant",
            documentation=None
         )
      ]


####### Money types
@dataclass
class HeliosAssetClass(HeliosType):
   type_name: str = field(init=False, repr=False, default='AssetClass')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "Represents a unique token on the blockchain using its `MintingPolicyHash` and "
         "its token name (as a `ByteArray`)."
      )
   )

   def member_completions(self) -> List[HeliosFunction]:
      return [self._serialize]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | HeliosType]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               HeliosMintingPolicyHash(identifier="policy_hash", element="variable"),
               HeliosByteArray(identifier="token_name", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Constructs a new `AssetClass` using a `MintingPolicyHash` and a token name `ByteArray`."
               )
            )
         ),
         cls(
            identifier="ADA",
            element="constant",
            documentation=None
         )
      ]


@dataclass
class HeliosValue(HeliosType):
   type_name: str = field(init=False, repr=False, default='Value')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "The `Value` type represents monetary value as a token bundle. This is internally represented "
         "as a `Map[MintingPolicyHash]Map[ByteArray]Int`."
      )
   )

   def operators(self) -> List[str]:
      return [">=", ">", "<=", "<", '+', '-', '*', '/'] + self._innate_operators # special case in parse_binary_expression

   def member_completions(self) -> List[HeliosFunction]:
      return [
         self._serialize,
         HeliosFunction(
            identifier="contains",
            element="method",
            parameters=[HeliosValue(identifier="other_value", element="variable")],
            return_type=HeliosBool(),
            documentation=None
         ),
         HeliosFunction(
            identifier="contains_policy",
            element="method",
            parameters=[HeliosMintingPolicyHash(identifier="mph", element="variable")],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if a given `MintingPolicyHash` is in a `Value`."
               )
            )
         ),
         HeliosFunction(
            identifier="get",
            element="method",
            parameters=[HeliosAssetClass(identifier="asset_class", element="variable")],
            return_type=HeliosInt(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns the amount of the given `AssetClass` present in the `Value`. Throws an error "
                  "if the `AssetClass` isn't found."
               )
            )
         ),
         HeliosFunction(
            identifier="get_policy",
            element="method",
            parameters=[HeliosMintingPolicyHash(identifier="mph", element="variable")],
            return_type=factory_map_type(HeliosByteArray, HeliosInt)(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns a map of tokens of the given `MintingPolicyHash` present in the `Value`. Throws an error "
                  "if the `MintingPolicyHash` isn't found."
               )
            )
         ),
         HeliosFunction(
            identifier="is_zero",
            element="method",
            parameters=[],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value="Checks if the `Value` is empty."
            )
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | HeliosType]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               HeliosAssetClass(identifier="asset_class", element="variable"),
               HeliosInt(identifier="amount", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns a `Value` containing an amount of a given `AssetClass`."
               )
            )
         ),
         HeliosFunction(
            identifier="from_map",
            element="function",
            parameters=[
               factory_map_type(
                  HeliosMintingPolicyHash, factory_map_type(
                     HeliosByteArray, HeliosInt
                  )
               )(identifier="map", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Instantiate a `Value` from a Helios map."
               )
            )
         ),
         HeliosFunction(
            identifier="lovelace",
            element="function",
            parameters=[HeliosInt(identifier="amount", element="variable")],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns a `Value` containing only lovelace."
               )
            )
         ),
         cls(
            identifier="ZERO",
            element="constant",
            documentation=None
         )
      ]


####### Transaction types
@dataclass
class HeliosCredential(HeliosType):
   type_name: str = field(init=False, repr=False, default='Credential')
   container_kind: str = field(init=False, repr=False, default='enum')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "Represents the non-staking part of an `Address`. Internally represented as an enum with two variants: "
         "`PubKey` (wrapper of `PubKeyHash`) & `Validator` (wrapper of `ValidatorHash`).\n"
         "Example instantiation:\n"
         "\tpubkey_credential: `Credential`::`PubKey` = `Credential`::`new_pubkey`(`PubKeyHash`::`new`(#...)); ...\n"
         "\tvalidator_credential: `Credential`::`Validator` = `Credential`::`new_validator`(`ValidatorHash`::`new`(#...)); ..."
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
      return [self._serialize, switch_kw]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
      return [
         cls._from_data(),
         factory_enum_variant_type(
            variant_name='PubKey',
            variant_fields=[
               HeliosPubKeyHash(
                  identifier="hash",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::PubKey",
            has_from_data=True
         ),
         factory_enum_variant_type(
            variant_name='Validator',
            variant_fields=[
               HeliosValidatorHash(
                  identifier="hash",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::Validator",
            has_from_data=True
         ),
         HeliosFunction(
            identifier="new_pubkey",
            element="function",
            parameters=[HeliosPubKeyHash(identifier="pkh", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='PubKey',
               variant_fields=[
                  HeliosPubKeyHash(
                     identifier="hash",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::PubKey",
               has_from_data=True
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_validator",
            element="function",
            parameters=[HeliosValidatorHash(identifier="vh", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Validator',
               variant_fields=[
                  HeliosValidatorHash(
                     identifier="hash",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::Validator",
               has_from_data=True
            )(),
            documentation=None
         )
      ]


@dataclass
class HeliosStakingCredential(HeliosType):
   type_name: str = field(init=False, repr=False, default='StakingCredential')
   container_kind: str = field(init=False, repr=False, default='enum')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "Represents the staking part of an `Address`. `StakingCredential` is an enum with 2 variants: "
         "`Hash` & `Ptr`."
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
      return [self._serialize, switch_kw]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
      return [
         cls._from_data(),
         factory_enum_variant_type(
            variant_name='Hash',
            variant_fields=[],
            enum_name=f"{cls.type_name}::Hash"
         ),
         factory_enum_variant_type(
            variant_name='Ptr',
            variant_fields=[],
            enum_name=f"{cls.type_name}::Ptr"
         ),
         HeliosFunction(
            identifier="new_hash",
            element="function",
            parameters=[HeliosCredential(identifier="credential", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Hash',
               variant_fields=[],
               enum_name=f"{cls.type_name}::Hash"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_ptr",
            element="function",
            parameters=[
               HeliosInt(identifier="a", element="variable"),
               HeliosInt(identifier="b", element="variable"),
               HeliosInt(identifier="c", element="variable")
            ],
            return_type=factory_enum_variant_type(
               variant_name='Ptr',
               variant_fields=[],
               enum_name=f"{cls.type_name}::Ptr"
            )(),
            documentation=None
         )
      ]


@dataclass
class HeliosAddress(HeliosType):
   type_name: str = field(init=False, repr=False, default='Address')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value="Cardano address."
   )

   def member_completions(self) -> List[HeliosFunction | HeliosType]:
      return [
         self._serialize,
         HeliosCredential(
            identifier="credential",
            element="property",
            documentation=None
         ),
         factory_option_type(HeliosStakingCredential)(identifier="staking_credential", element="property")
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | HeliosType]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               HeliosCredential(identifier="credential", element="variable"),
               factory_option_type(HeliosStakingCredential)(identifier="staking_credential", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Construct a new `Address` from a `Credential` and an optional `StakingCredential`."
               )
            )
         )
      ]


@dataclass
class HeliosDCert(HeliosType):
   type_name: str = field(init=False, repr=False, default='DCert')
   container_kind: str = field(init=False, repr=False, default='enum')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "Represents an enum of staking related actions:\n"
         "\t`Register`: register a `StakingCredential`\n"
         "\t`Deregister`: deregister a `StakingCredential`\n"
         "\t`Delegate`: delegate a `StakingCredential` to a pool\n"
         "\t`RegisterPool`: register a pool\n"
         "\t`RetirePool`: deregister a pool\n"
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
      return [self._serialize, switch_kw]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
      return [
         cls._from_data(),
         factory_enum_variant_type(
            variant_name='Register',
            variant_fields=[
               HeliosStakingCredential(
                  identifier="credential",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::Register"
         ),
         factory_enum_variant_type(
            variant_name='Deregister',
            variant_fields=[
               HeliosStakingCredential(
                  identifier="credential",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::Deregister"
         ),
         factory_enum_variant_type(
            variant_name='Delegate',
            variant_fields=[
               HeliosStakingCredential(
                  identifier="delegator",
                  element="property",
                  documentation=None
               ),
               HeliosPubKeyHash(
                  identifier="pool_id",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::Delegate"
         ),
         factory_enum_variant_type(
            variant_name='RegisterPool',
            variant_fields=[
               HeliosPubKeyHash(
                  identifier="pool_id",
                  element="property",
                  documentation=None
               ),
               HeliosPubKeyHash(
                  identifier="pool_vrf",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::RegisterPool"
         ),
         factory_enum_variant_type(
            variant_name='RetirePool',
            variant_fields=[
               HeliosPubKeyHash(
                  identifier="pool_id",
                  element="property",
                  documentation=None
               ),
               HeliosInt(
                  identifier="epoch",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::RetirePool"
         ),
         HeliosFunction(
            identifier="new_register",
            element="function",
            parameters=[HeliosStakingCredential(identifier="credential", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Register',
               variant_fields=[
                  HeliosStakingCredential(
                     identifier="credential",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::Register"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_deregister",
            element="function",
            parameters=[HeliosStakingCredential(identifier="credential", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Deregister',
               variant_fields=[
                  HeliosStakingCredential(
                     identifier="credential",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::Deregister"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_delegate",
            element="function",
            parameters=[
               HeliosStakingCredential(identifier="delegator", element="variable"),
               HeliosPubKeyHash(identifier="pool_id", element="variable")
            ],
            return_type=factory_enum_variant_type(
               variant_name='Delegate',
               variant_fields=[
                  HeliosStakingCredential(
                     identifier="delegator",
                     element="property",
                     documentation=None
                  ),
                  HeliosPubKeyHash(
                     identifier="pool_id",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::Delegate"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_register_pool",
            element="function",
            parameters=[
               HeliosPubKeyHash(identifier="pool_id", element="variable"),
               HeliosPubKeyHash(identifier="pool_vrf", element="variable")
            ],
            return_type=factory_enum_variant_type(
               variant_name='RegisterPool',
               variant_fields=[
                  HeliosPubKeyHash(
                     identifier="pool_id",
                     element="property",
                     documentation=None
                  ),
                  HeliosPubKeyHash(
                     identifier="pool_vrf",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::RegisterPool"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_retire_pool",
            element="function",
            parameters=[
               HeliosPubKeyHash(identifier="pool_id", element="variable"),
               HeliosInt(identifier="epoch", element="variable")
            ],
            return_type=factory_enum_variant_type(
               variant_name='RetirePool',
               variant_fields=[
                  HeliosPubKeyHash(
                     identifier="pool_id",
                     element="property",
                     documentation=None
                  ),
                  HeliosInt(
                     identifier="epoch",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::RetirePool"
            )(),
            documentation=None
         )
      ]


@dataclass
class HeliosStakingPurpose(HeliosType):
   type_name: str = field(init=False, repr=False, default='StakingPurpose')
   container_kind: str = field(init=False, repr=False, default='enum')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "A staking purpose script has a `StakingPurpose`, which is an enum with 2 variants: `Rewarding` & `Certifying`."
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
      return [self._serialize, switch_kw]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
      return [
         cls._from_data(),
         factory_enum_variant_type(
            variant_name='Rewarding',
            variant_fields=[
               HeliosStakingCredential(
                  identifier="credential",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::Rewarding"
         ),
         factory_enum_variant_type(
            variant_name='Certifying',
            variant_fields=[
               HeliosDCert(
                  identifier="dcert",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::Certifying"
         )
      ]


@dataclass
class HeliosTxId(HeliosType):
   type_name: str = field(init=False, repr=False, default='TxId')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value="This is a type-safe wrapper around `ByteArray` representing the hash of a transaction."
   )

   def member_completions(self) -> List[HeliosFunction]:
      return [self._serialize]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | HeliosType]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[HeliosByteArray(identifier="bytes", element="variable")],
            return_type=cls(documentation=None),
            documentation=None
         )
      ]


@dataclass
class HeliosTxOutputId(HeliosType):
   type_name: str = field(init=False, repr=False, default='TxOutputId')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "Represents the unique ID of a UTxO. It is composed of the transaction ID (`TxId`) of the "
         "transaction that created that UTxO, and of the index (`Int`) of that UTxO in the outputs of that transaction."
      )
   )

   def member_completions(self) -> List[HeliosFunction]:
      return [self._serialize]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | HeliosType]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               HeliosTxId(identifier="tx_id", element="variable"),
               HeliosInt(identifier="index", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=None
         )
      ]


@dataclass
class HeliosOutputDatum(HeliosType):
   type_name: str = field(init=False, repr=False, default='OutputDatum')
   container_kind: str = field(init=False, repr=False, default='enum')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "Represents that datum data of a `TxOutput` instance.\n"
         "`OutputDatum` is an enum with 3 variants: `None`, `Hash`, `Inline`."
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
      return [self._serialize, switch_kw]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
      return [
         cls._from_data(),
         factory_enum_variant_type(
            variant_name='None',
            variant_fields=[],
            enum_name=f"{cls.type_name}::None"
         ),
         factory_enum_variant_type(
            variant_name='Hash',
            variant_fields=[
               HeliosDatumHash(
                  identifier="hash",
                  element="property",
                  documentation=None
               )
            ],
            enum_name=f"{cls.type_name}::Hash"
         ),
         factory_enum_variant_type(
            variant_name='Inline',
            variant_fields=[
               HeliosData(
                  identifier="data",
                  element="property",
                  documentation=MarkupContent(
                     kind=MarkupKind.Markdown,
                     value=(
                        "Use the `from_data` associated function, which is automatically defined "
                        "on every type, to turn `Data` into another type."
                     )
                  )
               )
            ],
            enum_name=f"{cls.type_name}::Inline"
         ),
         HeliosFunction(
            identifier="new_none",
            element="function",
            parameters=[],
            return_type=factory_enum_variant_type(
               variant_name='None',
               variant_fields=[],
               enum_name=f"{cls.type_name}::None"
            )(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `OutputDatum`::`None` instance."
               )
            )
         ),
         HeliosFunction(
            identifier="new_hash",
            element="function",
            parameters=[HeliosDatumHash(identifier="datum_hash", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Hash',
               variant_fields=[
                  HeliosDatumHash(
                     identifier="hash",
                     element="property",
                     documentation=None
                  )
               ],
               enum_name=f"{cls.type_name}::Hash"
            )(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `OutputDatum`::`Hash` instance."
               )
            )
         ),
         HeliosFunction(
            identifier="new_inline",
            element="function",
            parameters=[HeliosTypeParameter(identifier="any", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Inline',
               variant_fields=[
                  HeliosData(
                     identifier="data",
                     element="property",
                     documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=(
                           "Use the `from_data` associated function, which is automatically defined "
                           "on every type, to turn `Data` into another type."
                        )
                     )
                  )
               ],
               enum_name=f"{cls.type_name}::Inline"
            )(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `OutputDatum`::`Inline` instance."
               )
            )
         )
      ]


@dataclass
class HeliosTxOutput(HeliosType):
   type_name: str = field(init=False, repr=False, default='TxOutput')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value="Represents a transaction output."
   )

   def member_completions(self) -> List[HeliosFunction | HeliosType]:
      return [
         self._serialize,
         HeliosAddress(
            identifier="address",
            element="property",
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value="The address at which the `TxOutput` is sitting."
            )
         ),
         HeliosValue(
            identifier="value",
            element="property",
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value="`Value` locked in the `TxOutput`."
            )
         ),
         HeliosOutputDatum(
            identifier="datum",
            element="property",
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value="Datum of the `TxOutput` as an `OutputDatum` instance."
            )
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               HeliosAddress(identifier="address", element="variable"),
               HeliosValue(identifier="value", element="variable"),
               HeliosOutputDatum(identifier="datum", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `TxOutput` instance."
               )
            )
         )
      ]


@dataclass
class HeliosTxInput(HeliosType):
   type_name: str = field(init=False, repr=False, default='TxInput')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value="Represents a transaction input."
   )

   def member_completions(self) -> List[HeliosFunction | HeliosType]:
      return [
         self._serialize,
         HeliosTxOutputId(
            identifier="output_id",
            element="property",
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value="The `TxOutputId` of the underlying UTxO."
            )
         ),
         HeliosTxOutput(
            identifier="output",
            element="property",
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value="The underlying UTxO as a `TxOutput`."
            )
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               HeliosTxOutputId(identifier="output_id", element="variable"),
               HeliosTxOutput(identifier="output", element="variable"),
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `TxInput` instance."
               )
            )
         )
      ]


@dataclass
class HeliosScriptPurpose(HeliosType):
   type_name: str = field(init=False, repr=False, default='ScriptPurpose')
   container_kind: str = field(init=False, repr=False, default='enum')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "Each redemption in a transaction has a ScriptPurpose with the following 4 variants: "
         "`Minting`, `Spending`, `Rewarding`, `Certifying`.\n\t`ScriptPurpose`::`Rewarding` and `ScriptPurpose`::`Certifying` "
         "are identical to `StakingPurpose`::`Rewarding` and `StakingPurpose`::`Certifying` respectively, but the use cases "
         "are different.\n\t`StakingPurpose` is used for switching between rewarding and certifying within a given "
         "staking script. `ScriptPurpose` is used to see what other scripts are being used in the same transaction "
         "(see `tx.redeemers`)."
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosKeyword]:
      return [self._serialize, switch_kw]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction | Type[HeliosType]]:
      return [
         cls._from_data(),
         factory_enum_variant_type(
            variant_name='Minting',
            variant_fields=[
               HeliosMintingPolicyHash(
                  identifier="policy_hash",
                  element="property",
                  documentation=MarkupContent(
                     kind=MarkupKind.Markdown,
                     value=(
                        "`MintingPolicyHash` of the UTxO whose minting or burning is being validated."
                     )
                  )
               )
            ],
            enum_name=f"{cls.type_name}::Minting"
         ),
         factory_enum_variant_type(
            variant_name='Spending',
            variant_fields=[
               HeliosTxOutputId(
                  identifier="output_id",
                  element="property",
                  documentation=MarkupContent(
                     kind=MarkupKind.Markdown,
                     value=(
                        "`TxOutputId` of the UTxO whose spending is being validated."
                     )
                  )
               )
            ],
            enum_name=f"{cls.type_name}::Spending"
         ),
         factory_enum_variant_type(
            variant_name='Rewarding',
            variant_fields=[
               HeliosStakingCredential(
                  identifier="credential",
                  element="property",
                  documentation=MarkupContent(
                     kind=MarkupKind.Markdown,
                     value=(
                        "`StakingCredential` for which rewards are being withdrawn."
                     )
                  )
               )
            ],
            enum_name=f"{cls.type_name}::Rewarding"
         ),
         factory_enum_variant_type(
            variant_name='Certifying',
            variant_fields=[
               HeliosDCert(
                  identifier="dcert",
                  element="property",
                  documentation=MarkupContent(
                     kind=MarkupKind.Markdown,
                     value=(
                        "The current stake certifying action as a `DCert`."
                     )
                  )
               )
            ],
            enum_name=f"{cls.type_name}::Certifying"
         ),
         HeliosFunction(
            identifier="new_minting",
            element="function",
            parameters=[HeliosMintingPolicyHash(identifier="mph", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Minting',
               variant_fields=[
                  HeliosMintingPolicyHash(
                     identifier="policy_hash",
                     element="property",
                     documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=(
                           "`MintingPolicyHash` of the UTxO whose minting or burning is being validated."
                        )
                     )
                  )
               ],
               enum_name=f"{cls.type_name}::Minting"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_spending",
            element="function",
            parameters=[HeliosTxOutputId(identifier="output_id", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Spending',
               variant_fields=[
                  HeliosTxOutputId(
                     identifier="output_id",
                     element="property",
                     documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=(
                           "`TxOutputId` of the UTxO whose spending is being validated."
                        )
                     )
                  )
               ],
               enum_name=f"{cls.type_name}::Spending"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_rewarding",
            element="function",
            parameters=[HeliosStakingCredential(identifier="staking_credential", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Rewarding',
               variant_fields=[
                  HeliosStakingCredential(
                     identifier="credential",
                     element="property",
                     documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=(
                           "`StakingCredential` for which rewards are being withdrawn."
                        )
                     )
                  )
               ],
               enum_name=f"{cls.type_name}::Rewarding"
            )(),
            documentation=None
         ),
         HeliosFunction(
            identifier="new_certifying",
            element="function",
            parameters=[HeliosDCert(identifier="dcert", element="variable")],
            return_type=factory_enum_variant_type(
               variant_name='Certifying',
               variant_fields=[
                  HeliosDCert(
                     identifier="dcert",
                     element="property",
                     documentation=MarkupContent(
                        kind=MarkupKind.Markdown,
                        value=(
                           "The current stake certifying action as a `DCert`."
                        )
                     )
                  )
               ],
               enum_name=f"{cls.type_name}::Certifying"
            )(),
            documentation=None
         )
      ]


@dataclass
class HeliosTx(HeliosType):
   type_name: str = field(init=False, repr=False, default='Tx')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value="Represents a balanced transaction."
   )

   def member_completions(self) -> List[HeliosFunction | HeliosType]:
      return [
         self._serialize,
         factory_list_type(HeliosTxInput)(identifier="inputs", element="property"),
         factory_list_type(HeliosTxInput)(identifier="ref_inputs", element="property"),
         factory_list_type(HeliosTxOutput)(identifier="outputs", element="property"),
         HeliosValue(identifier="fee", element="property"),
         HeliosValue(identifier="minted", element="property"),
         factory_list_type(HeliosDCert)(identifier="dcerts", element="property"),
         factory_map_type(HeliosStakingCredential, HeliosInt)(identifier="withdrawals", element="property"),
         HeliosTimeRange(identifier="time_range", element="property"),
         factory_list_type(HeliosPubKeyHash)(identifier="signatories", element="property"),
         factory_map_type(HeliosScriptPurpose, HeliosData)(identifier="redeemers", element="property"),
         HeliosTxId(identifier="id", element="property"),
         HeliosFunction(
            identifier="is_signed_by",
            element="method",
            parameters=[HeliosPubKeyHash(identifier="pkh", element="variable")],
            return_type=HeliosBool(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns `true` if the transaction was signed by the given `PubKeyHash`."
               )
            )
         ),
         HeliosFunction(
            identifier="find_datum_hash",
            element="method",
            parameters=[HeliosTypeParameter(identifier="data", element="variable")],
            return_type=HeliosDatumHash(),
            documentation=None
         ),
         HeliosFunction(
            identifier="outputs_sent_to",
            element="method",
            parameters=[HeliosPubKeyHash(identifier="pkh", element="variable")],
            return_type=factory_list_type(HeliosTxOutput)(),
            documentation=None
         ),
         HeliosFunction(
            identifier="outputs_sent_to_datum",
            element="method",
            parameters=[
               HeliosPubKeyHash(identifier="pkh", element="variable"),
               HeliosTypeParameter(identifier="datum", element="variable"),
               HeliosBool(identifier="is_inline", element="variable")
            ],
            return_type=factory_list_type(HeliosTxOutput)(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns the `TxOutputs` sent to a regular payment address tagged with the "
                  "given datum (datum tagging can be used to prevent double satisfaction exploits)."
               )
            )
         ),
         HeliosFunction(
            identifier="outputs_locked_by",
            element="method",
            parameters=[HeliosValidatorHash(identifier="script_hash", element="variable")],
            return_type=factory_list_type(HeliosTxOutput)(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns the `TxOutputs` locked at the given script address."
               )
            )
         ),
         HeliosFunction(
            identifier="outputs_locked_by_datum",
            element="method",
            parameters=[
               HeliosValidatorHash(identifier="script_hash", element="variable"),
               HeliosTypeParameter(identifier="datum", element="variable"),
               HeliosBool(identifier="is_inline", element="variable")
            ],
            return_type=factory_list_type(HeliosTxOutput)(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns the `TxOutputs` locked at the given script address with the given datum."
               )
            )
         ),
         HeliosFunction(
            identifier="value_sent_to",
            element="method",
            parameters=[HeliosPubKeyHash(identifier="pkh", element="variable")],
            return_type=HeliosValue(),
            documentation=None
         ),
         HeliosFunction(
            identifier="value_sent_to_datum",
            element="method",
            parameters=[
               HeliosPubKeyHash(identifier="pkh", element="variable"),
               HeliosTypeParameter(identifier="datum", element="variable"),
               HeliosBool(identifier="is_inline", element="variable")
            ],
            return_type=HeliosValue(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns the `Value` sent to a regular payment address tagged with the "
                  "given datum (datum tagging can be used to prevent double satisfaction exploits)."
               )
            )
         ),
         HeliosFunction(
            identifier="value_locked_by",
            element="method",
            parameters=[HeliosValidatorHash(identifier="script_hash", element="variable")],
            return_type=HeliosValue(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns the output `Value` locked at the given script address."
               )
            )
         ),
         HeliosFunction(
            identifier="value_locked_by_datum",
            element="method",
            parameters=[
               HeliosValidatorHash(identifier="script_hash", element="variable"),
               HeliosTypeParameter(identifier="datum", element="variable"),
               HeliosBool(identifier="is_inline", element="variable")
            ],
            return_type=HeliosValue(),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Returns the output `Value` locked at the given script address with the given datum."
               )
            )
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new",
            element="function",
            parameters=[
               factory_list_type(HeliosTxInput)(identifier="inputs", element="variable"),
               factory_list_type(HeliosTxInput)(identifier="ref_inputs", element="variable"),
               factory_list_type(HeliosTxOutput)(identifier="outputs", element="variable"),
               HeliosValue(identifier="fee", element="variable"),
               HeliosValue(identifier="minted", element="variable"),
               factory_list_type(HeliosDCert)(identifier="dcerts", element="variable"),
               factory_map_type(HeliosStakingCredential, HeliosInt)(identifier="withdrawals", element="variable"),
               HeliosTimeRange(identifier="time_range", element="variable"),
               factory_list_type(HeliosPubKeyHash)(identifier="signatories", element="variable"),
               factory_map_type(HeliosScriptPurpose, HeliosTypeParameter)(identifier="redeemers", element="variable"),
               factory_map_type(HeliosDatumHash, HeliosTypeParameter)(identifier="datums", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `Tx` instance."
               )
            )
         )
      ]


@dataclass
class HeliosScriptContext(HeliosType):
   type_name: str = field(init=False, repr=False, default='ScriptContext')
   documentation = MarkupContent(
      kind=MarkupKind.Markdown,
      value=(
         "The `ScriptContext` contains all the metadata related to a signed Cardano transaction "
         "and is often an important argument of the validator script main function. It wraps the `Tx` "
         "type and provides some extra methods."
      )
   )

   def member_completions(self) -> List[HeliosFunction | HeliosType]:
      return [
         self._serialize,
         HeliosTx(identifier="tx", element="property"),
         HeliosFunction(
            identifier="get_spending_purpose_output_id",
            element="method",
            parameters=[],
            return_type=HeliosTxOutputId(),
            documentation=None
         ),
         HeliosFunction(
            identifier="get_current_input",
            element="method",
            parameters=[],
            return_type=HeliosTxInput(),
            documentation=None
         ),
         HeliosFunction(
            identifier="get_current_validator_hash",
            element="method",
            parameters=[],
            return_type=HeliosValidatorHash(),
            documentation=None
         ),
         HeliosFunction(
            identifier="get_current_minting_policy_hash",
            element="method",
            parameters=[],
            return_type=HeliosMintingPolicyHash(),
            documentation=None
         ),
         HeliosFunction(
            identifier="get_staking_purpose",
            element="method",
            parameters=[],
            return_type=HeliosStakingPurpose(),
            documentation=None
         )
      ]

   @classmethod
   def path_completions(cls) -> List[HeliosFunction]:
      return [
         cls._from_data(),
         HeliosFunction(
            identifier="new_spending",
            element="function",
            parameters=[
               HeliosTx(identifier="tx", element="variable"),
               HeliosTxOutputId(identifier="output_id", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `ScriptContext` instance."
               )
            )
         ),
         HeliosFunction(
            identifier="new_minting",
            element="function",
            parameters=[
               HeliosTx(identifier="tx", element="variable"),
               HeliosMintingPolicyHash(identifier="mph", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `ScriptContext` instance."
               )
            )
         ),
         HeliosFunction(
            identifier="new_rewarding",
            element="function",
            parameters=[
               HeliosTx(identifier="tx", element="variable"),
               HeliosStakingCredential(identifier="credential", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `ScriptContext` instance."
               )
            )
         ),
         HeliosFunction(
            identifier="new_certifying",
            element="function",
            parameters=[
               HeliosTx(identifier="tx", element="variable"),
               HeliosDCert(identifier="dcert", element="variable")
            ],
            return_type=cls(documentation=None),
            documentation=MarkupContent(
               kind=MarkupKind.Markdown,
               value=(
                  "Only available after `main`. Constructs a new `ScriptContext` instance."
               )
            )
         )
      ]
