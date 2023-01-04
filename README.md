# helios-language-server

[![image-version](https://img.shields.io/pypi/v/helios-language-server.svg)](https://python.org/pypi/helios-language-server)
[![image-python-versions](https://img.shields.io/badge/python=3.10-blue)](https://python.org/pypi/helios-language-server)
[![Downloads](https://static.pepy.tech/personalized-badge/helios-language-server?period=total&units=international_system&left_color=black&right_color=orange&left_text=Downloads)](https://pepy.tech/project/helios-language-server)

Language server for <a href="https://github.com/Hyperion-BT/Helios">Helios</a>, a non-Haskell Cardano smart contract language.
Uses the <a href="https://github.com/openlawlibrary/pygls">pygls</a> lsp framework and <a href="https://github.com/tree-sitter/tree-sitter">tree-sitter</a> for syntax tree generation.

![auto-complete](./img/auto-complete.gif)

## Requirements

* `Python 3.10`
* `python3-pip` (Ubuntu/Debian)
* `python3-venv` (Ubuntu/Debian)


## Installation

### coc.nvim
1. Easy way via npm package <a href="https://github.com/et9797/coc-helios">coc-helios</a>:

    `:CocInstall coc-helios`

2. Alternatively, if you know how to set up Python virtual environments:

    `python3 -m venv .venv` <br>
    `source .venv/bin/activate` <br>
    `pip install helios-language-server`
    
    Put this in your `coc-settings.json` file (`:CocConfig`):
    
    ```json
    {
        "languageserver": {
          "helios": {
            "command": "helios-language-server",
            "args": ["--stdio"],
            "filetypes": ["*.hl", "hl"]
        }
    }
    ```
    The language server should now activate whenever you open `.hl` files, provided you have `filetype.nvim` plugin installed. 

## Capabilities
- [x] Auto-completions
- [x] Syntax errors
- [ ] Hover
- [ ] Signature help
- [ ] Go to definition

## Comments and tips (**IMPORTANT**)
Currently only supports builtin types and methods up until Helios v0.9.2 (apart from import statements).

While in general the tree-sitter parser works fairly decently, there are several shortcomings as it is not always error tolerant. 
Meaning that if there are syntax errors present in the source, the parser could generate error nodes sometimes spanning the entire document. 
This will lead to no/unexpected auto-completions or underline the document with error diagnostics. 
To address the latter issue, it is ***highly*** recommended to add this line to your `init.vim`: `:hi CocErrorHighlight guifg=NONE`. 

Unfortunately, not too much can be done about the error recovery at this stage, as this is still also an open <a href="https://github.com/tree-sitter/tree-sitter/issues/1870#issuecomment-1248659929">issue</a> with tree-sitter. 
I have tried to address some commonly occuring parsing errors. A plugin I find useful is `Cosco.vim` which allows mapping a key to automatically insert `;` at the end of the line. 
In some cases this can fix the syntax tree and bring back completions, without having to move the cursor and staying in insert mode.

## To-dos
- VSCode support
- Hover
- Signature help information
- Parser improvements
- Advanced diagnostics
- Semantic highlighting
- Imports
- Support newer Helios versions
- Tree-sitter syntax highlighting
