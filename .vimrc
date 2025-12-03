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
let mapleader = ","
inoremap jj <Esc>
nnoremap j gj
nnoremap k gk
nnoremap <C-h> :bprevious<CR>
nnoremap <C-l> :bnext<CR>
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
  Plug 'junegunn/fzf'
  "Plug 'ziglang/zig.vim'
  Plug 'tpope/vim-surround'
  Plug 'tpope/vim-eunuch' "useful for :Rename, :Move
  Plug 'scrooloose/nerdcommenter'
  Plug 'ntpeters/vim-better-whitespace'
  Plug 'lambdalisue/suda.vim'
  Plug 'nvim-tree/nvim-web-devicons'

  "colorschemes
  Plug 'EvitanRelta/vim-colorschemes'
  "Plug 'navarasu/onedark.nvim'
  "Plug 'sainnhe/sonokai'
  "Plug 'rktjmp/lush.nvim'
  "Plug 'ViViDboarder/wombat.nvim'
  "Plug 'Mofiqul/vscode.nvim'
  "Plug 'EdenEast/nightfox.nvim'
  "Plug 'tiagovla/tokyodark.nvim'

  "Plug 'mhinz/vim-grepper'
  if has('nvim')
    Plug 'neovim/nvim-lspconfig'
    Plug 'nvim-treesitter/nvim-treesitter', {'do': ':TSUpdate'}
    " similar plugins, mostly barebones, render all buffers as visual "tabs", with some differences like sorting
    "Plug 'ap/vim-buftabline'
    Plug 'romgrk/barbar.nvim'
    Plug 'LunarVim/bigfile.nvim'
    Plug 'folke/trouble.nvim'
    set signcolumn=number
    set updatetime=300
  endif
call plug#end()

" https://cj.rs/blog/git-ls-files-is-faster-than-fd-and-find/
" https://github.com/junegunn/fzf/blob/master/README-VIM.md
" https://github.com/junegunn/fzf/issues/31
function! FZFExecute()
  " Remove trailing new line to make it work with tmux splits
  let directory = substitute(system('git rev-parse --show-toplevel'), '\n$', '', '')
  if !v:shell_error
    call fzf#run({'sink': 'e', 'dir': directory, 'source': 'git ls-files -c --exclude-standard', 'window': { 'width': 0.9, 'height': 0.6 } })
  else
    FZF
  endif
endfunction
command! FZFExecute call FZFExecute()

function! FZFCWDExecute()
  " Remove trailing new line to make it work with tmux splits
  if !v:shell_error
    call fzf#run({'sink': 'e', 'dir': '.', 'window': { 'width': 0.9, 'height': 0.6 } })
  else
    FZF
  endif
endfunction
command! FZFCWDExecute call FZFCWDExecute()

let $FZF_DEFAULT_COMMAND = 'fd --type f --exclude .git'
nnoremap <C-p> :FZFExecute<CR>
nnoremap <C-.> :FZFCWDExecute<CR>

let g:vim_markdown_folding_disabled = 1
let g:vim_markdown_new_list_item_indent = 0
let g:strip_whitespace_on_save = 1
let g:strip_whitespace_confirm = 0
let g:suda_smart_edit = 1

"colorscheme terafox
"colorscheme wombat256mod
"colorscheme wombat_classic
colorscheme onedark
" https://stackoverflow.com/a/7616332/198348
highlight Normal guibg=black guifg=white

if has('termguicolors')
  set termguicolors
endif

if !has('nvim')
  finish
endif

lua << EOF
-- vim.lsp.enable('pyright')
vim.lsp.enable('clangd')
vim.lsp.enable('ruff')

require("trouble").setup({})

require'barbar'.setup {
  auto_hide = true,
}

-- https://github.com/nvim-treesitter/nvim-treesitter
require'nvim-treesitter.configs'.setup {
  ensure_installed = { "java", "cpp", "rust", "python", "javascript", "jsonc", "typescript", "tsx", "bash", "markdown", "vim", "lua" },
  highlight = {
    enable = true,
    -- Setting this to true will run `:h syntax` and tree-sitter at the same time.
    -- Set this to `true` if you depend on 'syntax' being enabled (like for indentation).
    -- Using this option may slow down your editor, and you may see some duplicate highlights.
    -- Instead of true it can also be a list of languages
    additional_vim_regex_highlighting = "vim"
  }, incremental_selection = {
    enable = true,
    keymaps = {
      init_selection = "gnn",
      node_incremental = "grn",
      scope_incremental = "grc",
      node_decremental = "grm",
    },
  },
}
EOF

nnoremap <C-h> :BufferPrevious<CR>
nnoremap <C-l> :BufferNext<CR>
nnoremap <Leader>bc :BufferClose<CR>
nnoremap <Leader>bw :BufferWipeout<CR>

" https://github.com/folke/trouble.nvim?tab=readme-ov-file#lazynvim
" Leader-xx is useful, unsure about the others
nnoremap <leader>xx :Trouble diagnostics toggle<CR>
nnoremap <leader>xX :Trouble diagnostics toggle filter.buf=0<CR>
nnoremap <leader>cs :Trouble symbols toggle focus=false<CR>
nnoremap <leader>cl :Trouble lsp toggle focus=false win.position=right<CR>
nnoremap <leader>xL :Trouble loclist toggle<CR>
nnoremap <leader>xQ :Trouble qflist toggle<CR>
