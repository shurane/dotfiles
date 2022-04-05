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
let mapleader = ","
nnoremap j gj
nnoremap k gk
"nnoremap 0 g0
"nnoremap $ g$
inoremap jj <Esc>
nnoremap k gk
nnoremap j gj
nnoremap <C-l> :set hlsearch!<CR>
nnoremap <Leader>tw :set wrap!<CR>
nnoremap <Leader>tl :set list!<CR>
nnoremap <CR> o<Esc>
nnoremap \r :e $MYVIMRC<CR>
nnoremap <Leader>r :source $MYVIMRC<CR>
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
    Plug 'ziglang/zig.vim'
    Plug 'tpope/vim-surround'
    Plug 'tpope/vim-eunuch' " useful for :Rename, :Move
    Plug 'scrooloose/nerdcommenter'
    Plug 'ntpeters/vim-better-whitespace'
    Plug 'flazz/vim-colorschemes'
    Plug 'sheerun/vim-polyglot'
    " Plug 'mhinz/vim-grepper'
    " something for neovim
    if has('nvim')
        Plug 'neovim/nvim-lspconfig'
        " https://github.com/neoclide/coc.nvim
        Plug 'neoclide/coc.nvim', {'branch': 'release'}
        set signcolumn=number
        set updatetime=300
    endif

call plug#end()

colorscheme wombat256mod
nnoremap <C-p> :FZF<CR>

let g:vim_markdown_folding_disabled = 1
let g:vim_markdown_new_list_item_indent = 0
let g:strip_whitespace_on_save = 1
let g:strip_whitespace_confirm = 0

if !has('nvim')
  finish
endif

lua << EOF
require'lspconfig'.pyright.setup{}
require'lspconfig'.clangd.setup{}
EOF

" https://github.com/neoclide/coc.nvim/wiki/Using-coc-extensions#install-extensions
" maybe: coc-pairs
let g:coc_global_extensions = ['coc-pyright', 'coc-clangd', 'coc-highlight', 'coc-pairs']


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
