from __future__ import annotations
from typing import Union
from pygls.server import LanguageServer
from pygls.lsp.types import (
   CompletionList, CompletionOptions, CompletionParams, Hover, HoverParams,
   SignatureHelp, SignatureHelpParams, SignatureHelpOptions,
   DidOpenTextDocumentParams, DidChangeTextDocumentParams
)
from tree_sitter import Node
from .hlparser import parse_source, HELIOS_LANGUAGE
from .namespace import NamespaceParser
from .completer import Completer
from .hover import Hoverer
from .signature_helper import SignatureHelper
from .diagnostics import validate_document
from loguru import logger


logger.add("/tmp/ls.log", level="DEBUG", format='{time:HH:mm:ss.SSS} ({name}:{function}:{line}) - {message}')

server = LanguageServer(name="helios-language-server", version="0.3.0")
ns_parser = NamespaceParser()
completer = Completer(ns_parser)
hoverer = Hoverer(ns_parser)
signature_helper = SignatureHelper(ns_parser)


@server.feature('textDocument/didOpen')
def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
   # check src for syntax errors upon opening the file
   uri = params.text_document.uri
   doc = ls.workspace.get_document(uri)
   tree = parse_source(doc.source)
   validate_document(ls, uri, tree)


@server.feature('textDocument/didChange')
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
   logger.debug(f'{"#"*50}')
   uri = params.text_document.uri
   doc = ls.workspace.get_document(uri)
   global tree # global syntax tree object is updated each time the source code is changed
   tree = parse_source(doc.source)

   # syntax error diagnostics
   validate_document(ls, uri, tree)


@server.feature('textDocument/completion', CompletionOptions(trigger_characters=['.', ':']))
def completions(ls: LanguageServer, params: CompletionParams) -> CompletionList:
   """Returns completion items."""
   position = completer.position_from_params(params)
   try:
      if params.context.trigger_character == ':':
         logger.debug("trigger char ::")
         line, char = position
         query = HELIOS_LANGUAGE.query("""("::") @trigger""")
         path_trigger: Node = query.captures(
            tree.root_node, start_point=(line, char), end_point=(line, char+1)
         )[0][0]
         if not path_trigger:
            return CompletionList(is_incomplete=False, items=[])
         completions = completer.infer_completions(tree, position, '::')
      elif params.context.trigger_character == '.':
         logger.debug("trigger char .")
         completions = completer.infer_completions(tree, position, '.')
      else:
         logger.debug("no trigger char")
         completions = completer.infer_completions(tree, position)
   except Exception as e:
      logger.error(e)
      completions = []
   finally:
      return CompletionList(
         is_incomplete=False,
         items=completions
      )


@server.feature('textDocument/hover')
def hover(ls: LanguageServer, params: HoverParams) -> Hover | None:
   """Displays documentation for the word under the cursor."""
   logger.debug(f'{"-"*50}')
   uri = params.text_document.uri
   doc = ls.workspace.get_document(uri)
   tree = parse_source(doc.source)

   word = doc.word_at_position(params.position)

   try:
      hover_txt: Union[Hover, None] = hoverer.infer_hover(tree, word, params)
   except Exception as e:
      logger.error(e)
      return None
   else:
      return hover_txt


@server.feature('textDocument/signatureHelp', SignatureHelpOptions(trigger_characters=['(', ',', '{']))
def signature_help(ls: LanguageServer, params: SignatureHelpParams) -> SignatureHelp | None:
   """Returns function/struct literal signature help."""
   logger.debug(f'{"$"*50}')
   uri = params.text_document.uri
   doc = ls.workspace.get_document(uri)
   tree = parse_source(doc.source)

   try:
      signature_help: Union[SignatureHelp, None] = signature_helper.infer_signature(tree, doc, params)
   except Exception as e:
      logger.error(e)
      return None
   else:
      return signature_help


def main() -> None:
   server.start_io()


if __name__ == "__main__":
   main()
