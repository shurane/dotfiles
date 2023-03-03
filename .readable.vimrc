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
set pastetoggle=,tp
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
nnoremap <Leader>sv :source $HOME/.vimrc<CR>
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
  Plug 'sainnhe/sonokai'
  Plug 'rktjmp/lush.nvim', {'branch': 'main'}
  Plug 'ViViDboarder/wombat.nvim', {'branch': 'main'}
  Plug 'Mofiqul/vscode.nvim', {'branch': 'main'}
  Plug 'EdenEast/nightfox.nvim', {'branch': 'main'}
  Plug 'tiagovla/tokyodark.nvim'

  "Plug 'mhinz/vim-grepper'
  if has('nvim')
    Plug 'neovim/nvim-lspconfig'
    Plug 'nvim-treesitter/nvim-treesitter', {'do': ':TSUpdate'}
    " :TSInstall cpp python javascript jsonc vim zig html
    " https://github.com/neoclide/coc.nvim
    " similar plugins, mostly barebones, render all buffers as visual "tabs", with some differences like sorting
    "Plug 'ap/vim-buftabline'
    Plug 'romgrk/barbar.nvim'
    Plug 'neoclide/coc.nvim', {'branch': 'release'}
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
require'lspconfig'.pyright.setup{}
require'lspconfig'.clangd.setup{}

-- https://github.com/nvim-treesitter/nvim-treesitter
require'nvim-treesitter.configs'.setup {
  ensure_installed = { "java", "cpp", "python", "javascript", "typescript", "tsx", "bash", "markdown" },
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

" use barbar.nvim
let g:bufferline = {
  \ 'auto_hide': 1
\ }

nnoremap <C-h> :BufferPrevious<CR>
nnoremap <C-l> :BufferNext<CR>
nnoremap <Leader>bc :BufferClose<CR>
nnoremap <Leader>bw :BufferWipeout<CR>

" https://github.com/neoclide/coc.nvim/wiki/Using-coc-extensions#install-extensions
" maybe: coc-pairs
let g:coc_global_extensions = ['coc-pyright', 'coc-clangd', 'coc-highlight', 'coc-pairs']

" h :coc#on_enter(), https://github.com/neoclide/coc-pairs
inoremap <silent><expr> <cr> pumvisible() ? coc#_select_confirm()
      \: "\<C-g>u\<CR>\<c-r>=coc#on_enter()\<CR>"

" https://github.com/neoclide/coc.nvim#example-vim-configuration
nnoremap <silent> K :call <SID>show_documentation()<CR>

function! s:show_documentation()
  if (index(['vim','help'], &filetype) >= 0)
    execute 'h '.expand('<cword>')
  else
    call CocActionAsync('doHover')
  endif
endfunction

" Highlight the symbol and its references when holding the cursor.
autocmd CursorHold * silent call CocActionAsync('highlight')

" Use <c-space> to trigger completion.
inoremap <silent><expr> <c-space> coc#refresh()

" GoTo code navigation.
nmap <silent> gd <Plug>(coc-definition)
nmap <silent> gy <Plug>(coc-type-definition)
nmap <silent> gi <Plug>(coc-implementation)
nmap <silent> gr <Plug>(coc-references)

" Symbol renaming.
nmap <leader>rn <Plug>(coc-rename)

" Formatting selected code.
xmap <leader>f  <Plug>(coc-format-selected)
nmap <leader>f  <Plug>(coc-format-selected)
