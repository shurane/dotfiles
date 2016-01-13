set nocompatible               " be iMproved

filetype off                   " required!
set runtimepath+=~/.vim/bundle/neobundle.vim/

" Required:
call neobundle#begin(expand('~/.vim/bundle/'))

" Let NeoBundle manage NeoBundle
" Required:
NeoBundleFetch 'Shougo/neobundle.vim'

" My Bundles here:
"
" original repos on github
NeoBundle 'Shougo/neocomplete'
NeoBundle 'Shougo/vimproc.vim'
NeoBundle 'airblade/vim-gitgutter'
"NeoBundle 'gregsexton/gitv'
NeoBundle 'kien/ctrlp.vim'
"NeoBundle 'majutsushi/tagbar'
NeoBundle 'mbbill/undotree'
NeoBundle 'michalbachowski/vim-wombat256mod'
NeoBundle 'mileszs/ack.vim'
NeoBundle 'nathanaelkane/vim-indent-guides'
NeoBundle 'paradigm/TextObjectify'
NeoBundle 'scrooloose/nerdcommenter'
"NeoBundle 'scrooloose/nerdtree'
NeoBundle 'scrooloose/syntastic'
NeoBundle 'sheerun/vim-polyglot'
"NeoBundle 'sjl/clam.vim'
NeoBundle 'tpope/vim-eunuch'
NeoBundle 'tpope/vim-fugitive'
NeoBundle 'tpope/vim-markdown'
NeoBundle 'tpope/vim-repeat'
NeoBundle 'tpope/vim-rsi'
NeoBundle 'tpope/vim-surround'
NeoBundle 'tpope/vim-unimpaired'
NeoBundle 'vim-scripts/matchit.zip'
NeoBundle 'luochen1990/rainbow'
NeoBundle 'wlangstroth/vim-racket'

" vim-scripts repos
" non github repos
call neobundle#end()

NeoBundleCheck

filetype plugin indent on     " required!
syntax enable

" Vim Settings {{{

set t_Co=256                " colors!
colorscheme wombat256mod
set history=10000           " keep n lines of history
set bs=2                    " set backspace to wrap around to previous line
set whichwrap=~,[,]         " Wrap around lines with ~, left-arrow key, and right-arrow key
set number                  " enable line numbering
set numberwidth=5           " set line numbering to take up 5 lines
set cursorline              " highlights current line

set ruler                   " show the cursor position all the time
set nowrap                  " don't wrap long lines
set linebreak               " don't wrap in the middle of words
set showbreak=>\ \ \        " for wrapped lines
set lcs=trail:-,extends:>,tab:>-,eol:$   " indicates trailing spaces by '-',  wrapped lines by '>', and tabs by '>-'
set scrolloff=3             " scroll up/down by n instead of 1
set showcmd                 " display incomplete command
set cmdheight=1             " set command bar height
set vb t_vb=""              " Turn visual bell off
set mouse=a                 " use the mouse in console vim
set mousehide

set splitright              " vertical splits split to the right (instead of left)
set clipboard+=unnamed      " yanks go onto the global clipboard as well -- this might make a mapping unnecessary

" very informative status line, but should document later
set statusline=%F%m%r%h%w\ [TYPE=%Y\ %{&ff}]\ [%l/%L\ (%p%%)]%=%{fugitive#statusline()}
set laststatus=2            " always keep status line on

set noautochdir               " don't always switch to the current file directory
set modeline                " allow vim options to be embedded in files
set modelines=5             " found either in first n lines or last n lines
set noautowrite             " don't write on make/shell, and other commands
set autoread                " reload changed files
set hidden                  " look this up -- something about efficient writing
set backup                  " simple backup
set backupext=~             " backup for 'file' is 'file~'
set lazyredraw              " don't redraw vim during macros and stuff. Force with :redraw

let required_dirs = ['$HOME/.vim','$HOME/.vim/backup','$HOME/.vim/swap','$HOME/.vim/undo']
for dir in required_dirs
    if finddir(expand(dir)) == ''
        call mkdir(expand(dir))
    endif
endfor

set backupdir=~/.vim/backup " stores all backups here
set directory=~/.vim/swap   " stores all swap files here

"set nowrapscan              " turn off search wrap
set incsearch               " turn on incremental search
set ignorecase              " ignore case for searching
set smartcase               " exclude explicit CAPS from ignorecase

set autoindent              " Turn on auto indent
set tabstop=4               " set tab character to n space
set expandtab               " turn tabs into whitespace
set softtabstop=4           " n spaces are treated as tabs
set shiftwidth=4            " indent width for autoindent
"set foldmethod=marker      " for explicit folds

set cpoptions=yraABceFq
set formatoptions+=tcq
" this formatoption isn't working, it seems
set formatoptions-=r        " don't insert comment after <CR>

au BufWritePost,BufNewFile,BufRead *.md,*.markdown,*.mdown,*.mkd,*.mkdn set filetype=markdown

" }}}

" Functions {{{

" trim whitespace, from http://vim.wikia.com/wiki/Remove_unwanted_spaces
function! StripTrailingWhitespace()
    normal mZ
    %s/\s\+$//e
    if line("'Z") != line(".")
        echo "Stripped whitespace"
    endif
    normal `Z
endfunction

" toggle syntax
function! ToggleSyntax()
    if exists("g:syntax_on")
        syntax off
    else
        syntax enable
    endif
endfunction

" toggle diff
function! ToggleDiff()
    if &diff
        diffoff
    else
        diffthis
    endif
endfunction

" }}}

" Vim Maps {{{

let mapleader = ","

" save a file as root
" quit without confirmation
" wipe buffer
" open new tab
" open up vimrc in current window
" reload .vimrc
cabbrev w!! w !sudo tee % > /dev/null<CR>:e!<CR><CR>
nnoremap \q :q!<CR>
nnoremap \bw :bw<CR>
nnoremap \t :tabedit<CR>
nnoremap \r :e $MYVIMRC<CR>
nnoremap <Leader>r :source $MYVIMRC<CR>

nnoremap <C-w>j <C-w>w
nnoremap <C-w>k <C-w>W
nnoremap <C-w><C-j> <C-w>w
nnoremap <C-w><C-k> <C-w>W

" switch back and forth between buffers
nnoremap `n :bn<CR>
nnoremap `p :bp<CR>
" switch back and forth between tabs
noremap <S-H> gT
noremap <S-L> gt
noremap j gj
noremap k gk

" mappings during insert mode
" when using C-u/C-w in insert mode, create a new change instead of appending
inoremap <C-u> <C-g>u<C-u>
inoremap <C-w> <C-g>u<C-w>
" escape while in insert-mode
inoremap jj <Esc>
" insert newline without going into insert-mode
nnoremap <CR> o<Esc>

" copy and paste to global clipboard using leader key
"nnoremap <Leader>v "+p
"vnoremap <Leader>v "+p
nnoremap <Leader>v <Leader>tp"+p<Leader>tp
vnoremap <Leader>v <Leader>tp"+p<Leader>tp
nnoremap <Leader>c "+yy
vnoremap <Leader>c "+y
nnoremap <Leader>y "+yy
vnoremap <Leader>y "+y
vnoremap <Leader>x "+d

" do :ls before switching buffers
nnoremap <Leader>b :ls<CR>:b

nnoremap <C-a> <Nop>
nnoremap <C-x> <Nop>

" Toggle different modes
" syntax, diff, paste, wrap, listchars, highlight, and scrollbind. Missing anything?
nnoremap <Leader>ts :call ToggleSyntax()<CR>
nnoremap <Leader>td :call ToggleDiff()<CR>
set pastetoggle=,tp
nnoremap <Leader>tw :set wrap!<CR>
nnoremap <Leader>tl :set list!<CR>
" add a second <C-l> after <CR> to redraw the screen
nnoremap <C-l> :set hlsearch!<CR>
nnoremap <Leader>tb :set scrollbind!<CR>

" stolen from @dirn
:iabbrev :shrug: ¯\_(ツ)_/¯
:iabbrev :tableflip: (╯°□°)╯︵ ┻━┻
" TODO kind of incomplete?
"nnoremap <Leader>tc :setlocal invspell spellang=en_us<CR>
" }}}

" Plugin Maps {{{

" CtrlP is pretty awesome
let g:ctrlp_user_command = {
    \ 'types': {
        \ 1: ['.git', 'cd %s && git ls-files'],
        \ 2: ['.hg', 'hg --cwd %s locate -I .'],
        \ },
    \ 'fallback': 'find %s -type f'
    \ }
let g:NERDCustomDelimiters = {
  \ 'racket': { 'left': ';', 'leftAlt': '#| ', 'rightAlt': ' |#' },
\ }

let g:neocomplete#enable_at_startup = 1
let g:tagbar_autofocus = 1
let g:indent_guides_auto_colors = 0
let g:indent_guides_guide_size = 1
let g:clam_autoreturn = 1
let g:syntastic_cpp_compiler = 'clang++'
let g:syntastic_cpp_compiler_options = ' -std=c++11 -stdlib=libc++'

autocmd VimEnter,Colorscheme * :hi IndentGuidesOdd  guibg=red   ctermbg=black
autocmd VimEnter,Colorscheme * :hi IndentGuidesEven guibg=green ctermbg=darkgrey
nnoremap <Leader>gg :UndotreeToggle<CR>
nnoremap <Leader>dd :TagbarToggle<CR>
nnoremap <Leader>ff :CtrlPBuffer<CR>
nnoremap <Leader>aa :NERDTreeToggle<CR>
nnoremap <Leader>ii :IndentGuidesToggle<CR>
nnoremap <Leader>ss :Ack 
" trailing space on <Leader>ss intentional

" }}}

" TODO {{{
" http://stackoverflow.com/questions/63104/smarter-vim-recovery
" or some better recovery method.

" }}}

" vim:fdm=marker:fdl=1
