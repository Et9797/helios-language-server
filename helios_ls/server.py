from __future__ import annotations
from pygls.server import LanguageServer
from pygls.lsp.types import (
   CompletionList, CompletionOptions, CompletionParams,
   DidChangeTextDocumentParams
)
from tree_sitter import Node
from .hlparser import parse_source, HELIOS_LANGUAGE
from .namespace import NamespaceParser
from .completer import Completer
from loguru import logger


logger.add("/tmp/ls.log", level="DEBUG", format='{time:HH:mm:ss.SSS} ({name}:{function}:{line}) - {message}')

server = LanguageServer()
ns_parser = NamespaceParser()
completer = Completer(ns_parser)


@server.feature('textDocument/didChange')
def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
   logger.debug('##################################################')
   uri = params.text_document.uri
   doc = ls.workspace.get_document(uri)
   global tree # global syntax tree object is updated each time the source code is changed
   tree = parse_source(doc.source)


@server.feature('textDocument/completion', CompletionOptions(trigger_characters=['.', ':']))
def completions(ls: LanguageServer, params: CompletionParams) -> CompletionList:
   """Returns completion items."""
   position = completer.position_from_params(params)
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

   return CompletionList(
      is_incomplete=False,
      items=completions
   )


def main() -> None:
   server.start_io()


if __name__ == "__main__":
   main()
