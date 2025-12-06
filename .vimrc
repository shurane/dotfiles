set nocp
set number
set ts=4
set sts=4
set sw=4
set expandtab
set bs=2
set scrolloff=3
set incsearch
set ignorecase
set linebreak
"set pastetoggle=,tp
set directory=$HOME/.vim/swapfiles/
set lcs=trail:-,extends:>,tab:>-,eol:$
set vb t_vb=
set splitright
set signcolumn=number
set updatetime=300
let mapleader = ","

" Basic mappings
inoremap jj <Esc>
nnoremap j gj
nnoremap k gk
nnoremap <C-s> :set hlsearch!<CR>
nnoremap <Leader>tw :set wrap!<CR>
nnoremap <Leader>tl :set list!<CR>
nnoremap <CR> o<Esc>
nnoremap <Leader>ev :e $HOME/.vimrc<CR>
nnoremap <Leader>eev :e $MYVIMRC<CR>
nnoremap <Leader>sv :source $MYVIMRC<CR>
vnoremap < <gv
vnoremap > >gv

" https://github.com/junegunn/vim-plug
" Automatic installaion of vim-plug and swapfiles creation
if empty(glob('~/.vim/autoload/plug.vim'))
  silent !mkdir -p ~/.vim/swapfiles
  silent !mkdir -p ~/.vim/autoload
  silent !curl -fLo ~/.vim/autoload/plug.vim
    \ https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim
  autocmd VimEnter * PlugInstall
endif

call plug#begin('~/.vim/plugged')
  " Fuzzy finding
  Plug 'junegunn/fzf'
  Plug 'ibhagwan/fzf-lua'

  " Editing enhancements
  Plug 'numToStr/Comment.nvim'
  Plug 'kylechui/nvim-surround'
  Plug 'windwp/nvim-autopairs'
  Plug 'echasnovski/mini.nvim'
  Plug 'tpope/vim-repeat'
  Plug 'tpope/vim-eunuch'
  Plug 'lambdalisue/suda.vim'

  " Git integration
  Plug 'tpope/vim-fugitive'
  Plug 'lewis6991/gitsigns.nvim'

  " File management
  Plug 'stevearc/oil.nvim'

  " UI enhancements
  Plug 'nvim-tree/nvim-web-devicons'
  Plug 'romgrk/barbar.nvim'
  Plug 'folke/which-key.nvim'

  " LSP and treesitter
  Plug 'neovim/nvim-lspconfig'
  Plug 'nvim-treesitter/nvim-treesitter', {'do': ':TSUpdate'}
  Plug 'folke/trouble.nvim'
  Plug 'LunarVim/bigfile.nvim'

  " Colorschemes
  Plug 'EvitanRelta/vim-colorschemes'
  "Plug 'navarasu/onedark.nvim'
  "Plug 'sainnhe/sonokai'
  "Plug 'rktjmp/lush.nvim'
  "Plug 'ViViDboarder/wombat.nvim'
  "Plug 'Mofiqul/vscode.nvim'
  "Plug 'EdenEast/nightfox.nvim'
  "Plug 'tiagovla/tokyodark.nvim'
call plug#end()

" Plugin settings
let g:vim_markdown_folding_disabled = 1
let g:vim_markdown_new_list_item_indent = 0
let g:suda_smart_edit = 1

" Colorscheme
colorscheme onedark
highlight Normal guibg=black guifg=white

if has('termguicolors')
  set termguicolors
endif

" fzf-lua keybindings
nnoremap <C-p> <cmd>lua require('fzf-lua').files()<CR>
nnoremap <leader>fg <cmd>lua require('fzf-lua').live_grep()<CR>
nnoremap <leader>fb <cmd>lua require('fzf-lua').buffers()<CR>
nnoremap <leader>fh <cmd>lua require('fzf-lua').help_tags()<CR>
nnoremap <leader>fo <cmd>lua require('fzf-lua').oldfiles()<CR>
nnoremap <leader>fl <cmd>lua require('fzf-lua').lsp_document_symbols()<CR>
nnoremap <leader>fs <cmd>lua require('fzf-lua').lsp_workspace_symbols()<CR>

" Buffer navigation (barbar.nvim)
nnoremap <C-h> :BufferPrevious<CR>
nnoremap <C-l> :BufferNext<CR>
nnoremap <Leader>bc :BufferClose<CR>
nnoremap <Leader>bw :BufferWipeout<CR>

" Trouble (diagnostics)
nnoremap <leader>xx :Trouble diagnostics toggle<CR>
nnoremap <leader>xX :Trouble diagnostics toggle filter.buf=0<CR>
nnoremap <leader>cs :Trouble symbols toggle focus=false<CR>
nnoremap <leader>cl :Trouble lsp toggle focus=false win.position=right<CR>
nnoremap <leader>xL :Trouble loclist toggle<CR>
nnoremap <leader>xQ :Trouble qflist toggle<CR>

" which-key
nnoremap <leader><leader> <cmd>WhichKey<CR>

" oil.nvim file explorer
nnoremap - <cmd>Oil<CR>

if !has('nvim')
  finish
endif

lua << EOF
-- LSP setup
vim.lsp.enable('clangd')
vim.lsp.enable('ruff')

-- LSP keybindings
vim.keymap.set('n', 'gd', vim.lsp.buf.definition, { desc = 'Go to definition' })
vim.keymap.set('n', 'gr', vim.lsp.buf.references, { desc = 'Go to references' })
vim.keymap.set('n', 'K', vim.lsp.buf.hover, { desc = 'Hover documentation' })
vim.keymap.set('n', '<leader>rn', vim.lsp.buf.rename, { desc = 'Rename symbol' })
vim.keymap.set('n', '<leader>ca', vim.lsp.buf.code_action, { desc = 'Code action' })
vim.keymap.set('n', '[d', vim.diagnostic.goto_prev, { desc = 'Previous diagnostic' })
vim.keymap.set('n', ']d', vim.diagnostic.goto_next, { desc = 'Next diagnostic' })

-- fzf-lua setup
require('fzf-lua').setup({
  winopts = {
    height = 0.85,
    width = 0.80,
    preview = {
      default = 'builtin',
      border = 'border',
      wrap = 'nowrap',
      hidden = 'nohidden',
    },
  },
  files = {
    git_icons = true,
    file_icons = true,
    fd_opts = "--color=never --type f --hidden --follow --exclude .git",
  },
})

-- gitsigns setup
require('gitsigns').setup({
  signs = {
    add          = { text = '+' },
    change       = { text = '~' },
    delete       = { text = '_' },
    topdelete    = { text = '‾' },
    changedelete = { text = '~' },
  },
  on_attach = function(bufnr)
    local gs = package.loaded.gitsigns

    vim.keymap.set('n', ']c', function()
      if vim.wo.diff then return ']c' end
      vim.schedule(function() gs.next_hunk() end)
      return '<Ignore>'
    end, {expr=true, buffer=bufnr, desc = 'Next hunk'})

    vim.keymap.set('n', '[c', function()
      if vim.wo.diff then return '[c' end
      vim.schedule(function() gs.prev_hunk() end)
      return '<Ignore>'
    end, {expr=true, buffer=bufnr, desc = 'Previous hunk'})

    vim.keymap.set('n', '<leader>hs', gs.stage_hunk, {buffer=bufnr, desc = 'Stage hunk'})
    vim.keymap.set('n', '<leader>hr', gs.reset_hunk, {buffer=bufnr, desc = 'Reset hunk'})
    vim.keymap.set('n', '<leader>hp', gs.preview_hunk, {buffer=bufnr, desc = 'Preview hunk'})
    vim.keymap.set('n', '<leader>hb', gs.blame_line, {buffer=bufnr, desc = 'Blame line'})
    vim.keymap.set('n', '<leader>tb', gs.toggle_current_line_blame, {buffer=bufnr, desc = 'Toggle inline blame'})
  end
})

-- Comment.nvim setup
require('Comment').setup()

-- nvim-surround setup
require('nvim-surround').setup()

-- nvim-autopairs setup
require('nvim-autopairs').setup()

-- mini.trailspace setup (whitespace management)
require('mini.trailspace').setup()

-- oil.nvim setup
require('oil').setup({
  default_file_explorer = true,
  columns = {
    "icon",
    "permissions",
    "size",
    "mtime",
  },
  view_options = {
    show_hidden = false,
  },
  keymaps = {
    ["g?"] = "actions.show_help",
    ["<CR>"] = "actions.select",
    ["<C-v>"] = "actions.select_vsplit",
    ["<C-x>"] = "actions.select_split",
    ["<C-t>"] = "actions.select_tab",
    ["<C-p>"] = "actions.preview",
    ["<C-c>"] = "actions.close",
    ["<C-l>"] = "actions.refresh",
    ["-"] = "actions.parent",
    ["_"] = "actions.open_cwd",
    ["`"] = "actions.cd",
    ["~"] = "actions.tcd",
    ["gs"] = "actions.change_sort",
    ["gx"] = "actions.open_external",
    ["g."] = "actions.toggle_hidden",
  },
})

-- which-key setup
require('which-key').setup()

-- barbar setup
require('barbar').setup({
  auto_hide = true,
})

-- trouble setup
require("trouble").setup({})

-- treesitter setup
require('nvim-treesitter.configs').setup({
  ensure_installed = { "java", "cpp", "rust", "python", "javascript", "jsonc", "typescript", "tsx", "bash", "markdown", "vim", "lua" },
  highlight = {
    enable = true,
    additional_vim_regex_highlighting = "vim"
  },
  incremental_selection = {
    enable = true,
    keymaps = {
      init_selection = "gnn",
      node_incremental = "grn",
      scope_incremental = "grc",
      node_decremental = "grm",
    },
  },
})
EOF
