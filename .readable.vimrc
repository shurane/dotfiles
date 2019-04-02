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
set pastetoggle=,tp 
set directory=$HOME/.vim/swapfiles/
set lcs=trail:-,extends:>,tab:>-,eol:$ 
set vb t_vb=
let mapleader = "," 
inoremap jj <Esc> 
nnoremap <C-l> :set hlsearch!<CR> 
nnoremap <Leader>tw :set wrap!<CR> 
nnoremap <Leader>tl :set list!<CR>
nnoremap <CR> o<Esc>
nnoremap \r :e $MYVIMRC<CR>
nnoremap <Leader>r :source $MYVIMRC<CR>

" https://github.com/junegunn/vim-plug
call plug#begin('~/.vim/plugged')

Plug 'junegunn/fzf'
Plug 'scrooloose/nerdcommenter'
Plug 'leafgarland/typescript-vim'
" Plug 'peitalin/vim-jsx-typescript'
Plug 'flazz/vim-colorschemes'

call plug#end()

colorscheme wombat256mod
nnoremap <C-p> :FZF<CR>

