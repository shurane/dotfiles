# Vim & Neovim Configuration

**Last Updated:** 2026-01-02

This repo contains two separate configurations:
- **`.vimrc`** - Pure Vim (vim-plug, Vimscript)
- **`nvim/`** - Neovim (lazy.nvim, Lua)

---

## Structure

```
dotfiles/
├── .vimrc                       # Vim config (single file)
└── nvim/
    ├── init.lua                 # Entry point
    ├── lazy-lock.json           # Plugin lockfile
    └── lua/
        ├── config/
        │   ├── options.lua      # Vim settings
        │   ├── keymaps.lua      # Basic keybindings
        │   └── lazy.lua         # Plugin manager bootstrap
        └── plugins/
            ├── completion.lua   # nvim-cmp
            ├── editor.lua       # Comment, surround, autopairs, oil, mini
            ├── fzf.lua          # Fuzzy finding
            ├── git.lua          # Fugitive, gitsigns
            ├── lsp.lua          # Language servers
            ├── treesitter.lua   # Syntax highlighting
            └── ui.lua           # Barbar, which-key, trouble, colorscheme
```

---

## Plugin Comparison

| Feature | Vim (.vimrc) | Neovim (nvim/) |
|---------|--------------|----------------|
| **Plugin Manager** | vim-plug | lazy.nvim |
| **Fuzzy Finder** | fzf.vim | fzf-lua |
| **Commenting** | vim-commentary | Comment.nvim |
| **Surround** | vim-surround | nvim-surround |
| **Auto Pairs** | auto-pairs | nvim-autopairs |
| **Whitespace** | vim-better-whitespace | mini.trailspace |
| **Git Signs** | vim-gitgutter | gitsigns.nvim |
| **File Explorer** | vim-vinegar (netrw) | oil.nvim |
| **Buffer Tabs** | vim-buftabline | barbar.nvim |
| **Which Key** | vim-which-key | which-key.nvim |
| **Icons** | vim-devicons | nvim-web-devicons |
| **LSP** | vim-lsp + vim-lsp-settings | nvim-lspconfig (native) |
| **Completion** | asyncomplete.vim | nvim-cmp |
| **Linting** | ALE | ruff (via LSP) |
| **Diagnostics UI** | Location list | trouble.nvim |
| **Syntax** | Vim regex | nvim-treesitter |
| **Big Files** | autocommand | bigfile.nvim |
| **Colorscheme** | onedark (vim-colorschemes) | onedark_dark (onedarkpro.nvim) |

### Shared Plugins (both configs)
- `junegunn/fzf` - fzf binary
- `tpope/vim-fugitive` - Git commands
- `tpope/vim-repeat` - Repeat plugin commands
- `tpope/vim-eunuch` - Unix commands
- `lambdalisue/suda.vim` - Sudo write

---

## LSP Servers

### Vim (.vimrc)
Manually registered, auto-installed by vim-lsp-settings:
```vim
clangd              " C/C++
pyright-langserver  " Python
typescript-language-server  " JS/TS
```

### Neovim (nvim/)
Native LSP, install servers separately:
```lua
vim.lsp.enable("clangd")   -- C/C++
vim.lsp.enable("pyright")  -- Python
vim.lsp.enable("ruff")     -- Python linting
vim.lsp.enable("bashls")   -- Bash
vim.lsp.enable("vtsls")    -- JS/TS
```

**Install commands:**
```bash
# Python
uv tool install pyright
uv tool install ruff

# JavaScript/TypeScript
npm install -g @vtsls/language-server

# Bash
npm install -g bash-language-server

# C/C++ (macOS)
brew install llvm
```

---

## Keybindings

**Leader:** `,` (comma) - both configs

### Common Keybindings (same in both)

| Key | Action |
|-----|--------|
| `<C-p>` | Find files |
| `<leader>fg` | Live grep |
| `<leader>fb` | Buffers |
| `<leader>fh` | Help tags |
| `<leader>fo` | Old files |
| `<C-h>` / `<C-l>` | Prev/next buffer |
| `<leader>bc` | Close buffer |
| `-` | File explorer |
| `<leader><leader>` | Which-key |
| `gd` | Go to definition |
| `gr` | References |
| `K` | Hover docs |
| `<leader>rn` | Rename |
| `<leader>ca` | Code action |
| `[d` / `]d` | Prev/next diagnostic |
| `[c` / `]c` | Prev/next git hunk |
| `<leader>hs` | Stage hunk |
| `<leader>hr` | Reset hunk |
| `<leader>hp` | Preview hunk |

### Vim-specific

| Key | Action |
|-----|--------|
| `<leader>fl` | BTags (buffer tags) |
| `<leader>fs` | Tags (project) |
| `<leader>xx` | Open location list |
| `<leader>xq` | Open quickfix |
| `gi` | Go to implementation |
| `gt` | Go to type definition |
| `Tab` / `S-Tab` | Navigate completion |
| `Enter` | Accept completion |

### Neovim-specific

| Key | Action |
|-----|--------|
| `<leader>fl` | LSP document symbols |
| `<leader>fs` | Grep current buffer |
| `<leader>ff` | Grep open buffers |
| `<leader>fw` | LSP workspace symbols |
| `<leader>fr` | LSP references (fzf) |
| `<leader>xx` | Trouble diagnostics |
| `<leader>cs` | Trouble symbols |
| `<leader>cl` | Trouble LSP |
| `gc` / `gb` | Comment toggle |
| `<leader>hb` | Git blame line |
| `<leader>tb` | Toggle inline blame |
| `<C-n>` / `<C-p>` | Navigate completion |
| `<C-y>` | Accept completion |
| `<C-Space>` | Trigger completion |

---

## Completion

### Vim (asyncomplete.vim)
- Auto-popup as you type
- `Tab` / `S-Tab` - navigate
- `Enter` - accept

### Neovim (nvim-cmp)
- Auto-popup on InsertEnter
- `<C-n>` / `<C-p>` - navigate
- `<C-y>` - accept
- `<C-Space>` - manual trigger
- Sources: LSP, buffer, path

---

## Installation

### Vim
```bash
# Plugins install automatically on first launch
vim

# Or manually:
vim +PlugInstall +qall

# Install LSP servers
npm install -g pyright typescript-language-server
```

### Neovim
```bash
# Plugins install automatically on first launch
nvim

# Or manually:
nvim "+Lazy sync" +qall

# Install LSP servers (see LSP section above)
```

---

## Plugin Management

### Vim (vim-plug)
```vim
:PlugInstall     " Install plugins
:PlugUpdate      " Update plugins
:PlugClean       " Remove unused
:PlugStatus      " Check status
```

### Neovim (lazy.nvim)
```vim
:Lazy            " Plugin UI
:Lazy sync       " Install + update + clean
:Lazy profile    " Startup time
:Lazy health     " Check health
```

---

## Files & Directories

### Vim
- Config: `~/.vimrc`
- Plugins: `~/.vim/plugged/`
- Swap: `~/.vim/swapfiles/`

### Neovim
- Config: `~/.config/nvim/`
- Plugins: `~/.local/share/nvim/lazy/`
- Swap: `~/.local/share/nvim/swap/`

---

## Troubleshooting

### Vim
```vim
:PlugStatus              " Check plugin status
:LspStatus               " Check LSP servers
:ALEInfo                 " Check ALE config
:verbose map <key>       " Check keybinding
```

### Neovim
```vim
:Lazy                    " Plugin status
:LspInfo                 " Check LSP servers
:checkhealth             " Full diagnostics
:checkhealth lsp         " LSP diagnostics
:verbose map <key>       " Check keybinding
```

---

## Key Differences Summary

| Aspect | Vim | Neovim |
|--------|-----|--------|
| Config language | Vimscript | Lua |
| LSP | vim-lsp (plugin) | Native |
| Treesitter | No | Yes |
| Diagnostics | ALE + loclist | Native + Trouble |
| Lazy loading | Manual | Built-in (lazy.nvim) |
| Startup time | Fast | Faster (lazy loading) |
| File explorer | netrw (built-in) | oil.nvim |
